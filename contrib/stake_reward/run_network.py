#!/usr/bin/env python3
"""SUPPLEMENTAL TEST ONLY. Real daemon RPC mining/native staking/P2P.
No production history, live wallets, configs, services or network peers are used.
"""
import argparse, base64, hashlib, json, os, secrets, signal, socket, struct, subprocess, sys, time, traceback, urllib.request, urllib.error
from pathlib import Path
from decimal import Decimal
# Parsing precedes all filesystem changes, so --help is side-effect free.
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--build-dir', required=True, type=Path, help='Output from build_network.py')
parser.add_argument('--run-root', type=Path, help='Outside-checkout parent for a new private run directory (default: build directory)')
parser.add_argument('--timeout-seconds', type=int, default=600, help='Overall scenario deadline, excluding bounded process cleanup (default: 600)')
args = parser.parse_args()
if sys.flags.optimize:
    parser.error('Do not use python -O: all block-validation assertions must execute')
if args.timeout_seconds <= 0:
    parser.error('--timeout-seconds must be positive')
ROOT = args.build_dir.resolve()
PARAMS = json.loads((ROOT/'network-parameters.json').read_text())
if not (PARAMS.get('test_only') is True and PARAMS.get('boundary') == 110
        and PARAMS.get('production_boundary') == 900000
        and PARAMS.get('magic') == '71a519e2' and PARAMS.get('bits') == '207fffff'
        and PARAMS.get('genesis') == '218d932966c127b715093e504b7f7cb221d788cec0ec5d4603f2ebe20bb2ef55'):
    parser.error('Unexpected private network parameters')
for name in ['netkod-patched-network', 'netkod-baseline-network']:
    if not os.access(ROOT/name, os.X_OK):
        parser.error('Missing executable: '+str(ROOT/name))
runroot = (args.run_root or ROOT).resolve()
# Reject paths in either this script's checkout or the recorded build checkout.
for checkout in [Path(__file__).resolve().parents[2], Path(PARAMS['source_dir']).resolve().parent]:
    if runroot == checkout or checkout in runroot.parents:
        parser.error('--run-root must be outside source checkouts')
runroot.mkdir(parents=True, exist_ok=True)
RUN = runroot/('run-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(6))
RUN.mkdir(mode=0o700)
DEADLINE = time.monotonic()+args.timeout_seconds
# Do not allow environment proxy settings to route private RPC off loopback.
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
NODES=[]
EVENTS=[]

def emit(event, **fields):
    data={'event':event,**fields}
    EVENTS.append(data)
    with (RUN/'events.jsonl').open('a') as f: f.write(json.dumps(data,sort_keys=True)+'\n')
    print(json.dumps(data,sort_keys=True),flush=True)

def freeport():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); return s.getsockname()[1]

def rpc(i,method,params=None):
    n=NODES[i]
    req=urllib.request.Request(f'http://127.0.0.1:{n["rpcport"]}/',data=json.dumps({'method':method,'params':params or [],'id':'private-test'}).encode(),headers={'Authorization':'Basic '+base64.b64encode(('private-test:'+n['password']).encode()).decode(),'Connection':'close'})
    try:
        with HTTP.open(req,timeout=max(.01, min(5, DEADLINE-time.monotonic()))) as r: data=json.load(r)
    except urllib.error.HTTPError as e:
        data=json.load(e)
    if data.get('error'): raise RuntimeError(f'{method}: {data["error"]}')
    return data['result']

def waitfor(fn,timeout=90,label='condition'):
    end=min(DEADLINE, time.monotonic()+timeout)
    last=None
    while time.monotonic()<end:
        try:
            value=fn()
            if value: return value
        except Exception as exc: last=repr(exc)
        time.sleep(.3)
    raise RuntimeError('Timed out '+label+' last='+str(last))

def start(i,staking=False):
    n=NODES[i]
    log=(n['path']/('stdout-staking.log' if staking else 'stdout.log')).open('a')
    n['loghandles'].append(log)
    n['proc']=subprocess.Popen(['stdbuf','-oL','-eL',str(n['binary']),'-datadir='+str(n['path']),'-testnet=1','-staking='+str(int(staking))],stdout=log,stderr=subprocess.STDOUT)
    waitfor(lambda: rpc(i,'getinfo'),label='startup '+str(i))

def stop(i):
    n=NODES[i]
    if n.get('proc') and n['proc'].poll() is None:
        rpc(i,'stop')
        rc=n['proc'].wait(timeout=max(.01, min(40, DEADLINE-time.monotonic())))
        assert rc==0,rc
        emit('clean_shutdown',node=i,exit=rc)

def dsha(b): return hashlib.sha256(hashlib.sha256(b).digest()).digest()
def varint(v):
    if v<253:return bytes([v])
    if v<65536:return b'\xfd'+struct.pack('<H',v)
    return b'\xfe'+struct.pack('<I',v)
def push(b): return bytes([len(b)])+b

def scriptheight(h):
    if 1<=h<=16:return bytes([0x50+h])
    b=h.to_bytes((h.bit_length()+7)//8,'little')
    if b[-1]&128:b+=b'\x00'
    return push(b)

def mine(height, script, timestamp, initial_template):
    # Preserve the native 600-second PoW target spacing, not a retarget bypass.
    # With identical spacing the compact target stays at the configured limit.
    # Historical early tips trip the native RPC-template IBD gate, so construct
    # subsequent headers from the first real RPC template; submitblock still
    # performs full ProcessBlock, retarget, signature, checkpoint validation.
    tpl=dict(initial_template)
    tpl['height']=height
    tpl['previousblockhash']=rpc(0,'getbestblockhash')
    assert initial_template['height']==1
    assert tpl['bits']=='207fffff'
    assert not tpl['transactions'],tpl['transactions']
    ss=scriptheight(height)+push(b'PR5-private-test')
    cb=struct.pack('<iI',1,timestamp)+b'\x01'+bytes(32)+b'\xff'*4+varint(len(ss))+ss+b'\xff'*4+b'\x01'+struct.pack('<q',tpl['coinbasevalue'])+varint(len(script))+script+bytes(4)
    header=struct.pack('<i',tpl['version'])+bytes.fromhex(tpl['previousblockhash'])[::-1]+dsha(cb)+struct.pack('<II',timestamp,int(tpl['bits'],16))
    target=int(tpl['target'],16)
    nonce=0
    while True:
        hdr=header+struct.pack('<I',nonce)
        digest=hashlib.blake2s(hdr).digest()
        if int.from_bytes(digest,'little')<=target:break
        nonce+=1
        assert nonce<20000000
    block=hdr+b'\x01'+cb+b'\x00'
    result=rpc(0,'submitblock',[block.hex()])
    assert result is None,(height,result)
    blockhash=digest[::-1].hex()
    assert rpc(0,'getblockhash',[height])==blockhash
    with (RUN/'pow-blocks.jsonl').open('a') as f:f.write(json.dumps({'height':height,'hash':blockhash,'bits':tpl['bits'],'time':timestamp,'nonce':nonce,'hex':block.hex()})+'\n')
    return blockhash

def block(i,h):return rpc(i,'getblock',[rpc(i,'getblockhash',[h]),True])

def main():
    ports=set()
    for i in range(4):
        n={'path':RUN/['producer','observer','old-validator','extra-peer'][i],'password':secrets.token_hex(32),'loghandles':[]}
        n['path'].mkdir(mode=0o700)
        for key in ['port','rpcport']:
            while True:
                p=freeport()
                if p not in ports:break
            ports.add(p);n[key]=p
        n['binary']=ROOT/('netkod-baseline-network' if i==2 else 'netkod-patched-network')
        NODES.append(n)
    for i,n in enumerate(NODES):
        conf=['rpcuser=private-test','rpcpassword='+n['password'],'rpcport='+str(n['rpcport']),'port='+str(n['port']),'bind=127.0.0.1:'+str(n['port']),'listen=1','server=1','daemon=0','dnsseed=0','discover=0','upnp=0','keypool=2','printtoconsole=1','logtimestamps=1','debug=coinstake','debug=net']
        # Exercise the corrected production format string only on patched nodes.
        # Baseline's inherited debug=creation bug aborts its staking thread.
        if i != 2: conf.append('debug=creation')
        # Star topology: three observers each connect only to the producer.
        conf+=['connect=127.0.0.1:'+str(NODES[0 if i else 1]['port'])]
        # Create owner-only from the first byte, not chmod after writing secrets.
        fd=os.open(n['path']/'netko.conf', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f: f.write('\n'.join(conf)+'\n')
    for i in range(4):start(i)
    socket_rows=[]
    for row in subprocess.check_output(['ss','-lntp'],text=True).splitlines()[1:]:
        fields=row.split()
        endpoint=fields[3]
        if any(endpoint.endswith(':'+str(p)) for p in ports):
            assert endpoint.startswith('127.0.0.1:') or endpoint.startswith('[::1]:'),endpoint
            socket_rows.append(row)
    assert all(any(row.split()[3].endswith(':'+str(p)) for row in socket_rows) for p in ports)
    (RUN/'loopback-listeners.json').write_text(json.dumps(socket_rows,indent=2))
    for i in range(4):
        assert rpc(i,'getblockcount')==0
        assert rpc(i,'getblockhash',[0])==PARAMS['genesis']
        assert rpc(i,'getinfo')['balance']==0
    waitfor(lambda: len(rpc(0,'getpeerinfo'))>=3,label='three loopback peers')
    for i in range(4):assert all(p['addr'].startswith('127.0.0.1:') for p in rpc(i,'getpeerinfo'))
    emit('private_genesis_and_peers',genesis=PARAMS['genesis'],peers=[len(rpc(i,'getpeerinfo')) for i in range(4)],run=str(RUN))
    # Initial genesis is old: let the unmodified IBD time gate expire.
    initial_template=waitfor(lambda: rpc(0,'getblocktemplate'),timeout=40,label='unmodified IBD gate')
    (RUN/'initial-rpc-template.json').write_text(json.dumps(initial_template,indent=2))
    addr=rpc(0,'getnewaddress')
    pub=rpc(0,'validateaddress',[addr])
    # Native wallet owns this ephemeral key. All PoW outputs use its P2PK script.
    key=bytes.fromhex(pub['pubkey'])
    script=push(key)+b'\xac'
    starttime=int(time.time())-500-109*600
    for h in range(1,110):
        bh=mine(h,script,starttime+600*h,initial_template)
        if h%10==0 or h==109:emit('mined_pow',height=h,hash=bh)
    waitfor(lambda: all(rpc(i,'getblockcount')==109 for i in range(4)),timeout=90,label='P2P PoW propagation 109')
    hashes=[rpc(i,'getbestblockhash') for i in range(4)]
    assert len(set(hashes))==1
    emit('pow_propagation_pass',height=109,hash=hashes[0],producer_balance=rpc(0,'getinfo')['balance'],stakeweight=rpc(0,'getstakinginfo')['weight'])
    stop(0)
    start(0,staking=True)
    # Restarting gives native staking the three real peers its sync gate requires.
    waitfor(lambda: len(rpc(0,'getpeerinfo'))>=3,timeout=90,label='producer reconnect')
    emit('native_staking_started',info=rpc(0,'getstakinginfo'))
    waitfor(lambda: rpc(0,'getblockcount')>=112,timeout=240,label='native wallet stakes through accelerated boundary')
    waitfor(lambda: rpc(1,'getblockcount')>=112 and rpc(3,'getblockcount')>=112,timeout=60,label='P2P corrected staking propagation')
    blocks=[]
    for h in [110,111,112]:
        b=block(0,h)
        assert b['flags'].startswith('proof-of-stake'),b
        assert len(b['tx'])==2,b['tx']
        assert Decimal(str(b['mint']))==(Decimal(25) if h==110 else Decimal('0.25')),b['mint']
        for i in [1,3]:assert rpc(i,'getblockhash',[h])==b['hash']
        blocks.append(b)
        emit('native_pos_verified',height=h,hash=b['hash'],mint=b['mint'],time=b['time'],observer_hash=rpc(1,'getblockhash',[h]))
    assert rpc(2,'getblockcount')==110
    assert rpc(2,'getbestblockhash')==blocks[0]['hash']
    waitfor(lambda: 'coinstake pays too much' in (NODES[2]['path']/'stdout.log').read_text(errors='replace').lower(),timeout=30,label='old-validator logged subsidy rejection')
    oldlog=(NODES[2]['path']/'stdout.log').read_text(errors='replace')
    assert 'coinstake pays too much' in oldlog.lower()
    emit('old_validator_rejection_pass',height=rpc(2,'getblockcount'),hash=rpc(2,'getbestblockhash'),reason='coinstake pays too much')
    (RUN/'boundary-blocks.json').write_text(json.dumps(blocks,indent=2))
    # Stop observer, allow a new real PoS block to appear, then restart and catch up.
    stop(1)
    offlineheight=rpc(0,'getblockcount')
    waitfor(lambda: rpc(0,'getblockcount')>offlineheight,timeout=90,label='new block while observer offline')
    catchheight=rpc(0,'getblockcount');catchhash=rpc(0,'getblockhash',[catchheight])
    assert catchheight>=113,catchheight
    start(1)
    waitfor(lambda: rpc(1,'getblockcount')>=catchheight,timeout=90,label='observer restart P2P resync')
    assert rpc(1,'getblockhash',[catchheight])==catchhash
    emit('restart_resync_pass',height=catchheight,hash=catchhash,offline_from=offlineheight)
    # Save public RPC evidence, never credentials or secret wallet material.
    evidence={'test_only':True,'parameters':PARAMS,'nodes':[{'name':n['path'].name,'height':rpc(i,'getblockcount'),'besthash':rpc(i,'getbestblockhash'),'peers':rpc(i,'getpeerinfo')} for i,n in enumerate(NODES)],'boundary_blocks':blocks,'restart_resync':{'height':catchheight,'hash':catchhash}}
    (RUN/'result.json').write_text(json.dumps(evidence,indent=2))
    for i in range(4):stop(i)
    emit('PASS',scope='accelerated private test chain, not mainnet height 900000 or release binaries',run=str(RUN))

def bounded_termination(signum, frame):
    raise SystemExit('bounded test termination (signal '+str(signum)+')')
signal.signal(signal.SIGTERM, bounded_termination)
signal.signal(signal.SIGINT, bounded_termination)
signal.signal(signal.SIGALRM, bounded_termination)
signal.setitimer(signal.ITIMER_REAL, args.timeout_seconds)

try:
    main()
except BaseException as e:
    emit('FAIL',error=repr(e),traceback=traceback.format_exc(),run=str(RUN))
    raise
finally:
    # Cleanup must survive the scenario deadline and repeated termination signals.
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # Signal all owned live children before waiting for any one of them.
    for n in NODES:
        p=n.get('proc')
        if p and p.poll() is None: p.terminate()
    cleanup_deadline=time.monotonic()+20
    for n in NODES:
        p=n.get('proc')
        if p and p.poll() is None:
            try: p.wait(timeout=max(.01, cleanup_deadline-time.monotonic()))
            except subprocess.TimeoutExpired: p.kill()
    for n in NODES:
        p=n.get('proc')
        if p and p.poll() is None: p.wait(timeout=10)
        for f in n['loghandles']: f.close()
    (RUN/'process-cleanup.json').write_text(json.dumps([{'node':i,'pid':n['proc'].pid,'returncode':n['proc'].poll()} for i,n in enumerate(NODES) if n.get('proc')],indent=2))
