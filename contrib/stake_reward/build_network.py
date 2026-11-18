#!/usr/bin/env python3
"""TEST ONLY: link private accelerated TestNet daemons from built wallet objects.

Never build release binaries with these parameters. Only throwaway output copies
are compiled; source files and existing objects are not modified.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess

BASELINE = '69d813fea6e3865b9d2622108c74d5f67dc27343'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Expected exactly one occurrence of ' + repr(old))
    return text.replace(old, new)


def header(bits, nonce):
    return (struct.pack('<i', 1) + bytes(32)
            + bytes.fromhex('b869fd250564a1c7bc1961c4585b056f8f0920ec638a5c237ef9b4b68e1d9b58')[::-1]
            + struct.pack('<III', 1488224842, bits, nonce))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', required=True, type=Path, help='Already-built wallet-enabled src directory')
    parser.add_argument('--output-dir', required=True, type=Path, help='New directory outside the source checkout; must not exist')
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument('--baseline-ref', default=BASELINE, help='Git revision supplying src/main.cpp')
    baseline.add_argument('--baseline-source', type=Path, help='Explicit baseline main.cpp file instead of git show')
    parser.add_argument('--deps-prefix', type=Path, default=os.environ.get('NETKO_DEPS'), help='Private dependency prefix (or NETKO_DEPS), containing include and lib/x86_64-linux-gnu')
    parser.add_argument('--openssl-prefix', type=Path, default=os.environ.get('NETKO_SSL'), help='Private OpenSSL prefix (or NETKO_SSL), containing include and lib')
    args = parser.parse_args()
    src, out = args.source_dir.resolve(), args.output_dir.resolve()
    checkout = src.parent
    if out == checkout or checkout in out.parents:
        parser.error('--output-dir must be outside the source checkout')
    if out.exists():
        parser.error('--output-dir already exists; choose a clean directory')
    compiler = shlex.split(os.environ.get('CXX', 'g++'))
    if not compiler:
        parser.error('CXX must name a compiler')
    patched = (src / 'main.cpp').read_text()
    if args.baseline_source:
        original_baseline = args.baseline_source.resolve().read_text()
        baseline_origin = str(args.baseline_source.resolve())
    else:
        original_baseline = subprocess.check_output(['git', '-C', str(checkout), 'show', args.baseline_ref + ':src/main.cpp'], text=True)
        baseline_origin = args.baseline_ref + ':src/main.cpp'
    chain_original = (src / 'chainparams.cpp').read_text()
    known = '0000397cab3008f491ad1a7428225fd0451f86b1ee46fb728ec16fc92cc7a47d'
    if hashlib.blake2s(header(0x1f00ffff, 70678)).digest()[::-1].hex() != known:
        raise RuntimeError('Original genesis header verification failed')
    nonce = 0
    while int.from_bytes(hashlib.blake2s(header(0x207fffff, nonce)).digest(), 'little') > (0x7fffff << (8 * 29)):
        nonce += 1
    genesis = hashlib.blake2s(header(0x207fffff, nonce)).digest()[::-1].hex()
    # Unique original patterns constrain all changes to the TestNet constructor.
    chain = chain_original
    for i, (old, new) in enumerate(zip(['5e', '83', '2f', 'd3'], ['71', 'a5', '19', 'e2'])):
        chain = replace_once(chain, f'pchMessageStart[{i}] = 0x{old};', f'pchMessageStart[{i}] = 0x{new};')
    chain = replace_once(chain, 'bnProofOfWorkLimit = CBigNum(~uint256(0) >> 16);', 'bnProofOfWorkLimit = CBigNum(~uint256(0) >> 1); // PRIVATE ACCELERATED TEST ONLY')
    chain = replace_once(chain, 'genesis.nNonce = 70678;', f'genesis.nNonce = {nonce}; // PRIVATE TEST GENESIS')
    chain = replace_once(chain, '0x' + known, '0x' + genesis)
    mains = {kind: replace_once(text, 'if (nHeight <= 900000)', 'if (nHeight <= 110) // PRIVATE ACCELERATED TEST ONLY; production boundary is 900000') for kind, text in [('patched', patched), ('baseline', original_baseline)]}
    base = ['make', '-f', 'makefile.unix', '-n', '-W', 'main.cpp', '-W', 'chainparams.cpp',
            'USE_UPNP=-', 'USE_WALLET=1', 'DEBUGFLAGS=',
            'CXX=' + shlex.join(compiler),
            'CXXFLAGS=-std=gnu++11 -ffunction-sections -fdata-sections']
    ldflags = ['-Wl,-z,noexecstack']
    if args.deps_prefix:
        prefix = args.deps_prefix.resolve()
        lib = prefix / 'lib/x86_64-linux-gnu'
        base += ['BOOST_INCLUDE_PATH=' + str(prefix / 'include'), 'BOOST_LIB_PATH=' + str(lib)]
        ldflags.append('-Wl,-rpath,' + str(lib))
    if args.openssl_prefix:
        prefix = args.openssl_prefix.resolve()
        base += ['OPENSSL_INCLUDE_PATH=' + str(prefix / 'include'), 'OPENSSL_LIB_PATH=' + str(prefix / 'lib')]
        ldflags.append('-Wl,-rpath,' + str(prefix / 'lib'))
    base += ['LDFLAGS=' + ' '.join(ldflags)]
    # -n is only a recipe source. Never execute make's generated shell scripts,
    # rebuild shared objects, or infer dependencies from an obj/*.o glob.
    dryrun = subprocess.check_output(base, cwd=src, text=True)
    commands = []
    for line in dryrun.splitlines():
        if line.strip().startswith(shlex.join(compiler) + ' '):
            cmd = shlex.split(line)
            if cmd[:len(compiler)] == compiler:
                commands.append(cmd)
    def unique(predicate, description):
        matches = [cmd for cmd in commands if predicate(cmd)]
        if len(matches) != 1:
            raise RuntimeError('Expected exactly one dry-run ' + description)
        return matches[0]
    compiles = {name: unique(lambda c, name=name: '-c' in c and c[-1] == name + '.cpp', name + ' compile') for name in ['main', 'chainparams']}
    link = unique(lambda c: '-c' not in c and '-o' in c and c[c.index('-o') + 1] == 'netkod', 'daemon link')
    for required in ['obj/main.o', 'obj/chainparams.o', 'obj/wallet.o', 'obj/miner.o', 'obj/bitcoind.o']:
        if link.count(required) != 1:
            raise RuntimeError('Missing/ambiguous wallet daemon link input: ' + required)
    inputs = [src / arg for arg in link if arg.endswith(('.o', '.a'))]
    for path in inputs:
        if not path.is_file():
            raise RuntimeError('Build the wallet-enabled daemon first; missing ' + str(path))
    for cmd in compiles.values():
        if '-DNDEBUG' in cmd or any(arg.startswith('-DNDEBUG=') for arg in cmd):
            raise RuntimeError('Genesis assertions must remain enabled')
    def rewrite_argv(command, replacements):
        for old in replacements:
            if command.count(old) != 1:
                raise RuntimeError('Expected exactly one compiler/linker argument: ' + old)
        return [replacements[arg] if arg in replacements else arg for arg in command]
    allcommands = []
    for name, origin in [('chainparams-network', 'chainparams'), ('main-patched-network', 'main'), ('main-baseline-network', 'main')]:
        replacements = {origin + '.cpp': str(out / (name + '.cpp')), 'obj/' + origin + '.o': str(out / (name + '.o')), 'obj/' + origin + '.d': str(out / (name + '.d'))}
        cmd = rewrite_argv(compiles[origin], replacements)
        for option in ['-o', '-MF']:
            if cmd.count(option) != 1 or not Path(cmd[cmd.index(option) + 1]).is_relative_to(out):
                raise RuntimeError('Unsafe compiler output: ' + option)
        allcommands.append(cmd)
    for kind in ['patched', 'baseline']:
        replacements = {'netkod': str(out / ('netkod-' + kind + '-network')), 'obj/main.o': str(out / ('main-' + kind + '-network.o')), 'obj/chainparams.o': str(out / 'chainparams-network.o')}
        allcommands.append(rewrite_argv(link, replacements))
    out.mkdir(mode=0o700, parents=True)
    def save_source(filename, diffname, original, changed):
        (out / filename).write_text(changed)
        (out / diffname).write_text(''.join(difflib.unified_diff(original.splitlines(True), changed.splitlines(True), fromfile='production/' + filename, tofile='test-only/' + filename)))
    save_source('chainparams-network.cpp', 'chainparams.diff', chain_original, chain)
    for kind, original in [('patched', patched), ('baseline', original_baseline)]:
        save_source('main-' + kind + '-network.cpp', 'main-' + kind + '.diff', original, mains[kind])
    (out / 'make-dry-run.txt').write_text(dryrun)
    (out / 'build-commands.json').write_text(json.dumps(allcommands, indent=2))
    (out / 'network-parameters.json').write_text(json.dumps({'test_only': True, 'boundary': 110, 'production_boundary': 900000, 'genesis': genesis, 'nonce': nonce, 'bits': '207fffff', 'magic': '71a519e2', 'baseline': baseline_origin, 'source_dir': str(src), 'make_argv': base, 'cwd': str(src), 'reused_inputs_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}, 'unchanged': 'all signature, kernel, retarget, checkpoints, maturity, reward arithmetic and ProcessBlock code'}, indent=2))
    for cmd in allcommands:
        print(shlex.join(cmd), flush=True)
        subprocess.run(cmd, cwd=src, check=True)
    print('PRIVATE_NETWORK_BUILD_PASS', genesis, nonce, flush=True)


if __name__ == '__main__':
    main()
