# Staking reward fix: verification and release gates

Recorded 18 November 2026. This document reports test evidence, **not approval of
monetary policy, activation, a release, or production deployment**.

## Changes under test

The original PR head was `ac14536b86e25fd7e4d8ca9c9a0a1d0c4aacfec8`, based on
`69d813fea6e3865b9d2622108c74d5f67dc27343`. Its corrected expression is
`25 * COIN / 100`, preserving 25 NETKO through height 900000 and proposing
0.25 NETKO afterwards. Previously, `25 / 100 * COIN` evaluated to zero before
multiplication. Fees are still added; positive-fee candidates can bypass the
wallet's zero-reward guard even on the old code.

Two narrowly related prerequisites were found during execution:

- The first DNS-seed string in `src/chainparams.cpp` lacked its closing quote,
  preventing a full build. The correction changes no endpoint or chain parameter.
- The reward debug log supplied three arguments to two format specifiers.
  `debug=creation` triggered a tinyformat exception and a native staking-thread
  abort. Adding `nHeight=%d` corrects the format without changing reward logic.

## Executed verification

### Compiled arithmetic and logging

The original extracted-function test passes 54 arithmetic cases across heights
1, 899999, 900000, 900001, 900002 and 1000000, three fee values and three coin
ages. The original arithmetic was independently reproduced failing at 900001
with zero fees (expected 25000000 atomic units, actual 0).

The new dependency-light logging test runs the extracted production call with
real tinyformat and fixture money formatting. It checks both boundary heights.
Full native creation logging is also exercised by the integration and patched
private-network runners; it is not inferred from the fixture logger alone.

### Full wallet-enabled Linux builds and production-height integration

The verified environment uses Ubuntu 24.04, GCC 13.3, private Boost 1.83, existing
private OpenSSL 1.0 and Berkeley DB 5.3. These are compatibility observations,
not a recommendation to replace system libraries or expose legacy services.

Both patched and base-comparison wallet-enabled daemons built. Actual production
`CWallet::CreateCoinStake`, signature/kernel preflight, disk-backed coin age,
input validation, LevelDB and `CBlock::ConnectBlock(..., false)` were exercised.
Each successful wallet-created stake was itself connected. Spent pointers,
mint/supply and transaction rollback/unspent readback were checked.

| Case | Patched | Baseline |
|---|---|---|
| Wallet at 900000, no fees | Creates/connects 25 NETKO | Same |
| Wallet at 900001, no fees | Creates/connects 0.25 NETKO | Cannot create stake |
| Wallet at 900001, 0.01 fee | Creates/connects 0.26 NETKO | Creates/connects fee-only 0.01 |
| Block at 900000, 25 NETKO | Accept | Accept |
| Historical reward + 1 atomic unit | Reject | Reject |
| Block at 900001, 0.25 NETKO | Accept | Reject |
| Post-boundary reward + 1 atomic unit | Reject | Reject |
| Zero-reward underclaim | Accept | Accept |
| Fee-only underclaim | Accept | Accept |
| 0.25 NETKO + explicit fee | Accept | Reject |
| 0.25 NETKO + fee + 1 atomic unit | Reject | Reject |

Each revision-specific run passes **3 wallet trials + 8 explicit block-connection
trials**. Running baseline with patched expectations fails at the fee-free wallet
trial after the historical wallet case succeeds. This negative control cannot
pass merely because setup failed. Enabling native creation logging reproduces
the original format exception; the corrected production call passes the same
integration with logging enabled.

The fixture's funding transaction is serialized/indexed, but its 302 ancestor
entries and high heights are seeded. This is **not** genesis-to-tip replay or the
complete `ProcessBlock`/`AcceptBlock` network context.

### Real accelerated private network

Four real daemons used fresh ephemeral wallets, actual loopback-only listeners
and explicit loopback peers. The driver mined 109 valid PoW blocks from private
genesis via native `submitblock`/`ProcessBlock`. Native wallet staking then
produced signed fee-free PoS blocks; observers received them through P2P.

For the original recorded rehearsal:

| Private height | Reward | Result |
|---|---:|---|
| 110 | 25 NETKO | All four validators accept |
| 111 | 0.25 NETKO | Patched observers accept; old validator rejects |
| 112 | 0.25 NETKO | Patched chain advances |
| 113 | 0.25 NETKO | Restarted patched observer catches up |

Final heights were 113 / 113 / 110 / 113. Patched nodes agreed on
`1a277ebc9a5f49a9cbaa5f7c4ccac26f8aacd00a8970b1aef9452efa9c8e1dd0`.
The old validator stopped at 110 and logged:

```text
coinstake pays too much(actual=25000000 vs calculated=0)
```

The original run exposed the debug-format crash separately and passed with that
category omitted. The published runner enables creation logging on patched nodes
to cover the correction. The baseline category stays disabled so its inherited
logging error does not obscure the monetary-policy incompatibility.

Publication verification reran the portable runners against the updated source,
including patched creation logging. It again passed native staking, old-validator
rejection and observer restart/catch-up, finishing at 113 / 113 / 110 / 113.
The new matching patched hash was
`c471d8051498a56faa7cac52720b1b6c92f46463a7fc0a35660b72d2e68e1766`.
Exact executable-source hashes and these results are recorded in the evidence JSON.

**Explicit test-only changes:** both variants accelerate the reward comparison
from 900000 to 110; private message magic, easy PoW limit and a remined/asserted
genesis isolate the chain. No reward arithmetic, signature, kernel, native
retarget, maturity or checkpoint check is bypassed. Exact generated diffs and
source/command hashes are retained by the builder. These binaries must never be
installed as release binaries or connected to public peers.

This network evidence supplements the exact production-height fixture. It is
not actual public-height continuation, full mainnet replay, a competing-branch
reorg test, GUI/other-platform verification, or proof of public-peer adoption.
The old/new rejection is direct evidence of coordinated-upgrade/chain-split risk.

## Reproduction and evidence

See `contrib/stake_reward/README.md` for executable commands, compatible build
requirements, fresh external output directories and the precise limits of each
check. The commands are manual verification; absence of required CI must not be
reported as a green CI result.

`doc/stake-reward-evidence.json` records public source identities and the
publication verification results. No real-wallet data, test RPC credentials,
private keys, datadir/database files or binary archives are committed.

## Remaining maintainer/release gates

- Confirm the intended post-boundary subsidy; apparent arithmetic intent is not
  an approved monetary policy.
- Decide whether the existing height boundary is appropriate or requires a
  separate activation plan; check for independently observed blocks beyond it.
- Review the complete final patch and package/verify actual release binaries for
  the intended supported platforms.
- Coordinate validating-node and staking-wallet upgrades. A walletless observer
  cannot produce stakes; upgrading one node does not establish chain recovery.
- Only after an approved rollout, verify advancing public tips and matching
  recent hashes across upgraded peers.

No production node/wallet was changed or restarted for these tests. No real
transaction or public block was broadcast. Test daemons were shut down and the
live observer remained at height 900000 during the recorded checks. Publication
of this PR does not authorize merging, releasing or deploying it.
