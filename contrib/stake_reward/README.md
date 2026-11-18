# Staking reward regression tests

These are test tools, **not release binaries or a public-chain activation plan**.
Never point them at a real wallet/datadir, peer or RPC endpoint. The scripts create
new isolated directories and ephemeral test wallets; retained run directories
contain test credentials and wallet keys and must not be published.

## Dependency-light checks

From the repository root, with Python 3 and a C++11 compiler:

```sh
python3 contrib/test_stake_reward.py
python3 contrib/test_stake_reward_logging.py
```

The first compiles the extracted production reward function and atomic-unit
constant for 54 arithmetic cases. Logging is disabled in that arithmetic test.
The second invokes the extracted production log call using the repository's real
tinyformat header. Only its money formatter/log sink are fixtures; it detects
format-argument mismatches and checks height context. It does not test native
log-category selection. The integration test below exercises that native path.

## Build prerequisites for native tests (Linux)

Use a separate checkout with compatible legacy dependencies and a C++11 compiler.
The verified environment used GCC 13, Boost 1.83, Berkeley DB 5.3 and an existing
private OpenSSL 1.0 installation. Do not replace system OpenSSL or install these
legacy dependencies globally just for this test. Full daemon dependencies remain
necessary; the test scripts do not download/install packages or use sudo.

Build LevelDB and wallet-enabled daemon objects with function/data sections:

```sh
make -C src/leveldb -j2 libleveldb.a libmemenv.a
(cd src && make -f makefile.unix -j2 USE_UPNP=- USE_WALLET=1 DEBUGFLAGS= \
  CXXFLAGS='-std=gnu++11 -ffunction-sections -fdata-sections')
```

Supply `BOOST_INCLUDE_PATH`, `BOOST_LIB_PATH`, `OPENSSL_INCLUDE_PATH`,
`OPENSSL_LIB_PATH` and private linker rpaths to make if dependencies are outside
system paths. Use the same compiler/dependencies for the test runners. `NETKO_DEPS`
and `NETKO_SSL` (or runner prefix arguments) select those existing prefixes; the
Boost prefix uses `include/` and `lib/x86_64-linux-gnu/`, OpenSSL uses `include/`
and `lib/`. Do not copy a real node's credential configuration into the checkout.

Use freshly built objects for the source being tested. The runners reuse those
objects; they do not prove stale objects match a modified checkout.

## Exact production-height integration

Choose a **new directory outside the source checkout** for each command. The
runner refuses an existing output directory and never overwrites daemon objects.
Use a complete Git checkout containing the baseline commit, or supply its public
`src/main.cpp` with `--baseline-source` when testing an exported source tree.

```sh
python3 contrib/stake_reward/run_integration.py \
  --source-dir "$PWD/src" --build-dir "$HOME/netko-tests/integration"
```

Optional prefix arguments: `--deps-prefix /private/boost-prefix` and
`--openssl-prefix /private/openssl-prefix`. The baseline defaults to upstream
`69d813fea6e3865b9d2622108c74d5f67dc27343`; override with `--baseline-ref` or an
explicit `--baseline-source` when reproducing another comparison.

The runner executes baseline expectations, patched expectations, an expected
baseline failure under patched expectations, and patched native creation logging.
Each successful revision run has **3 wallet trials + 8 explicit ConnectBlock
trials**; every successfully wallet-created stake is also connected. It checks
ECDSA/kernel/block signatures, nonzero disk-backed coin age, fee accounting,
excessive rewards, spent pointers, mint/supply and database rollback readback.

**Boundary:** this fixture seeds synthetic ancestry at the actual 900000/900001
boundary. It does not mine/replay that ancestry or call the complete network
`ProcessBlock` context. Do not present it as actual public-chain continuation.

## Supplemental accelerated private network

```sh
python3 contrib/stake_reward/build_network.py \
  --source-dir "$PWD/src" --output-dir "$HOME/netko-tests/private-network"
python3 contrib/stake_reward/run_network.py \
  --build-dir "$HOME/netko-tests/private-network"
```

The network builder accepts the same baseline-source/ref and dependency-prefix
options. The runner's `--help` lists its run-root/deadline options. Python 3.9+,
Linux `ss`, `stdbuf`, and the built native daemon dependencies are required.

The builder creates clearly separate **test-only** binaries. Both reward-height
comparisons become 110; private message magic, an easy PoW limit and a remined,
asserted genesis prevent confusion with the public network. Original source,
shared objects and release binaries are not modified. Reward arithmetic,
signatures, kernel, native retarget, maturity and checkpoints are not bypassed.

The runner starts four real daemons with fresh wallets and explicit loopback-only
peers. It mines 109 valid PoW blocks, enables native wallet staking through the
boundary, verifies matching patched P2P block hashes and old-validator rejection,
and checks observer restart/catch-up. Patched nodes enable `debug=creation` to
cover the corrected production log call. The old validator intentionally does
not enable that category because the baseline has the inherited format bug.

Timeouts are bounded and task-owned processes are stopped on failure. Fresh
run directories are retained for debugging; do not upload their configs,
wallets, databases or private keys. Public evidence can include exact source
diffs, build commands/hashes, decoded blocks, sanitized native logs, peer and
listener addresses, result JSON and cleanup status. Review before publishing.

**Boundary:** an accelerated private network is not a release-binary replay of
actual public height 900000. Competing-chain reorgs, full mainnet history and
public-peer adoption are not covered. Maintainer-approved monetary policy,
activation and coordinated validator/staker upgrade remain release gates.

See `doc/stake-reward-verification.md` for the recorded findings and evidence.
