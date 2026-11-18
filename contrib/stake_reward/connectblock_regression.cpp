// Isolated synthetic-chain integration fixture. NEVER run as a network node.
// Calls production ConnectBlock / CreateCoinStake / CheckProofOfStake unchanged.
#include "main.h"
#include "txdb.h"
#include "wallet.h"
#include "kernel.h"
#include "checkpoints.h"
#include "util.h"
#include <boost/filesystem.hpp>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <cstdlib>
#include <unistd.h>

static void Require(bool ok, const char* what) {
    if (!ok) throw std::runtime_error(what);
}
static const unsigned int NOW = 1700000000; // deterministic, not live time
static const int64_t PRINCIPAL = 1000 * COIN;
static const unsigned int BITS = 0x1e0fffff; // synthetic, not a claim of current difficulty

struct Fixture {
    CBasicKeyStore keys;
    CKey key;
    CScript pay;
    CTransaction funding;
    CBlock fundingBlock;
    std::vector<CBlockIndex> ancestry;
    std::vector<uint256> hashes;
    unsigned int file, pos;
    Fixture(CTxDB& db): ancestry(302), hashes(302) {
        key.MakeNewKey(true);
        Require(keys.AddKey(key), "add ephemeral key");
        pay << key.GetPubKey() << OP_CHECKSIG;
        funding.nTime = NOW - 86400;
        funding.vin.push_back(CTxIn());
        funding.vin[0].scriptSig = CScript() << 1 << 1;
        funding.vout.push_back(CTxOut(PRINCIPAL, pay));
        funding.vout.push_back(CTxOut(10 * COIN, pay));
        fundingBlock.nTime = funding.nTime;
        fundingBlock.nBits = BITS;
        fundingBlock.vtx.push_back(funding);
        fundingBlock.hashMerkleRoot = fundingBlock.BuildMerkleTree();
        Require(fundingBlock.WriteToDisk(file, pos), "write synthetic funding block");
        unsigned int txPos = pos + ::GetSerializeSize(CBlock(), SER_DISK, CLIENT_VERSION)
            - 2 * GetSizeOfCompactSize(0) + GetSizeOfCompactSize(fundingBlock.vtx.size());
        Require(db.AddTxIndex(funding, CDiskTxPos(file, pos, txPos), 0), "seed funding txindex");
        CTransaction roundtrip;
        CTxIndex idx;
        Require(roundtrip.ReadFromDisk(db, funding.GetHash(), idx), "read funding from real disk txindex");
        Require(roundtrip.GetHash() == funding.GetHash(), "funding serialization roundtrip");
        for (size_t i = 0; i < ancestry.size(); ++i) {
            hashes[i] = uint256(i + 100);
            ancestry[i].phashBlock = &hashes[i];
            ancestry[i].nFile = file;
            ancestry[i].nBlockPos = (i == 0 ? pos : pos + 100000 + i);
            ancestry[i].pprev = i ? &ancestry[i-1] : NULL;
            if (i) ancestry[i-1].pnext = &ancestry[i];
            ancestry[i].nTime = NOW - (ancestry.size()-i) * 16;
            ancestry[i].nBits = BITS;
            ancestry[i].nMoneySupply = 1010 * COIN;
        }
        hashes[0] = fundingBlock.GetHash();
        ancestry[0].hashMerkleRoot = fundingBlock.hashMerkleRoot;
    }
    void Height(int height) {
        for (size_t i = 0; i < ancestry.size(); ++i)
            ancestry[i].nHeight = height - int(ancestry.size()) + int(i);
        pindexBest = &ancestry.back();
        nBestHeight = pindexBest->nHeight;
        // ConnectInputs must NOT skip signature checking under checkpoints.
        Require(nBestHeight >= Checkpoints::GetTotalBlocksEstimate(), "height below checkpoint signature gate");
    }
    CTransaction Stake(int64_t reward) {
        CTransaction tx;
        tx.nTime = NOW;
        tx.vin.push_back(CTxIn(funding.GetHash(), 0));
        tx.vout.push_back(CTxOut(0, CScript()));
        tx.vout.push_back(CTxOut(PRINCIPAL + reward, pay));
        Require(SignSignature(keys, funding, tx, 0), "sign real stake input");
        Require(VerifySignature(funding, tx, 0, SCRIPT_VERIFY_NONE, 0), "verify real stake input");
        return tx;
    }
    CTransaction Fee(int64_t fee) {
        CTransaction tx;
        tx.nTime = NOW;
        tx.vin.push_back(CTxIn(funding.GetHash(), 1));
        tx.vout.push_back(CTxOut(10 * COIN - fee, pay));
        Require(SignSignature(keys, funding, tx, 0), "sign real fee input");
        Require(fee >= GetMinFee(tx), "fee fixture below production minimum");
        return tx;
    }
    CBlock Block(CTransaction stake, int64_t fee) {
        CBlock block;
        block.nTime = NOW;
        block.nBits = BITS;
        block.hashPrevBlock = pindexBest->GetBlockHash();
        CTransaction cb;
        cb.nTime = NOW;
        cb.vin.push_back(CTxIn());
        cb.vin[0].scriptSig = CScript() << pindexBest->nHeight + 1 << 1;
        cb.vout.push_back(CTxOut(0, CScript()));
        block.vtx.push_back(cb);
        block.vtx.push_back(stake);
        if (fee) block.vtx.push_back(Fee(fee));
        block.hashMerkleRoot = block.BuildMerkleTree();
        Require(key.Sign(block.GetHash(), block.vchBlockSig), "sign real PoS block");
        Require(block.CheckBlock(), "production CheckBlock preflight");
        Require(block.CheckBlockSignature(), "production block signature preflight");
        uint256 proof, target;
        Require(CheckProofOfStake(pindexBest, stake, BITS, proof, target), "production kernel + signature check");
        Require(CheckCoinStakeTimestamp(pindexBest->nHeight+1, block.nTime, stake.nTime), "production stake timestamp");
        return block;
    }
};

static void ConnectCase(CTxDB& db, Fixture& f, const char* name, int height,
                        int64_t reward, int64_t fee, bool expected) {
    f.Height(height);
    CTransaction stake = f.Stake(reward);
    uint64_t age = 0;
    Require(stake.GetCoinAge(db, pindexBest, age), "real coin age calculation");
    Require(age == 1000, "fixture must have nonzero disk-backed coin age");
    CBlock block = f.Block(stake, fee);
    unsigned int file, pos;
    Require(block.WriteToDisk(file, pos), "write candidate block");
    uint256 hash = block.GetHash();
    CBlockIndex index(file, pos, block);
    index.phashBlock = &hash;
    index.pprev = pindexBest;
    index.nHeight = height;
    Require(db.TxnBegin(), "begin isolated trial");
    bool accepted = block.ConnectBlock(db, &index, false);
    if (accepted) {
        CTxIndex previous, connected;
        Require(db.ReadTxIndex(f.funding.GetHash(), previous), "read back consumed funding");
        Require(!previous.vSpent[0].IsNull(), "ConnectBlock must mark stake prevout spent");
        Require(db.ReadTxIndex(stake.GetHash(), connected), "read back connected stake txindex");
        Require(index.nMint == reward, "ConnectBlock mint accounting");
        Require(index.nMoneySupply == 1010 * COIN + reward - fee, "ConnectBlock supply accounting");
    }
    Require(db.TxnAbort(), "abort isolated trial (also removes successful connection)");
    CTxIndex reset;
    Require(db.ReadTxIndex(f.funding.GetHash(), reset) && reset.vSpent[0].IsNull(), "trial rollback readback");
    std::cout << "CASE " << name << " height=" << height << " reward=" << reward
              << " fee=" << fee << " accepted=" << accepted << " expected=" << expected
              << " coin_age=" << age << std::endl;
    Require(accepted == expected, "ConnectBlock result mismatch");
    if (!accepted) Require(block.nDoS == 100, "rejection must be consensus DoS, not IO/setup failure");
}

static void WalletCase(CTxDB& db, Fixture& f, int height, int64_t fee, bool expected, int64_t reward) {
    f.Height(height);
    CWallet wallet; // memory-only, never wallet.dat
    Require(!wallet.fFileBacked, "wallet must not be persisted");
    Require(wallet.AddKey(f.key), "add ephemeral wallet key");
    CWalletTx wtx(&wallet, f.funding);
    wtx.hashBlock = f.fundingBlock.GetHash();
    wtx.vMerkleBranch = f.fundingBlock.GetMerkleBranch(0);
    wtx.nIndex = 0;
    wtx.MarkSpent(1); // reserve second funding output for explicit fee fixtures
    wallet.mapWallet[f.funding.GetHash()] = wtx;
    mapBlockIndex[wtx.hashBlock] = &f.ancestry[0];
    Require(wallet.GetBalance() == PRINCIPAL, "wallet fixture balance/maturity/merkle membership");
    CTransaction stake;
    stake.nTime = NOW;
    CKey returned;
    bool made = wallet.CreateCoinStake(wallet, BITS, 1, fee, stake, returned);
    std::cout << "WALLET height=" << height << " fee=" << fee << " created=" << made << " expected=" << expected << std::endl;
    Require(made == expected, "CreateCoinStake result mismatch");
    if (made) {
        Require(stake.IsCoinStake(), "wallet output coinstake marker");
        Require(stake.GetValueOut() - PRINCIPAL == reward, "wallet constructed output reward");
        Require(VerifySignature(f.funding, stake, 0, SCRIPT_VERIFY_NONE, 0), "wallet-generated stake signature");
        CBlock block = f.Block(stake, fee);
        uint256 proof, target;
        Require(CheckProofOfStake(pindexBest, stake, BITS, proof, target), "wallet-produced kernel");
        unsigned int file, pos;
        Require(block.WriteToDisk(file, pos), "write wallet-produced block");
        uint256 hash = block.GetHash();
        CBlockIndex index(file, pos, block);
        index.phashBlock = &hash;
        index.pprev = pindexBest;
        index.nHeight = height;
        Require(db.TxnBegin(), "begin wallet-produced connection trial");
        Require(block.ConnectBlock(db, &index, false), "connect actual wallet-produced stake");
        Require(index.nMint == reward, "wallet-produced mint accounting");
        Require(index.nMoneySupply == 1010 * COIN + reward - fee, "wallet-produced supply accounting");
        CTxIndex consumed;
        Require(db.ReadTxIndex(f.funding.GetHash(), consumed) && !consumed.vSpent[0].IsNull(), "wallet-produced stake spent readback");
        Require(db.TxnAbort(), "rollback wallet-produced connection");
        CTxIndex reset;
        Require(db.ReadTxIndex(f.funding.GetHash(), reset) && reset.vSpent[0].IsNull(), "wallet-produced rollback readback");
    }
    mapBlockIndex.erase(wtx.hashBlock);
}

int main(int argc, char** argv) {
    try {
        Require(argc == 3, "usage: harness patched|baseline EXISTING_EMPTY_SCRATCH_PARENT");
        std::string mode(argv[1]);
        Require(mode == "patched" || mode == "baseline", "unknown expected revision mode");
        boost::filesystem::path parent = boost::filesystem::canonical(argv[2]);
        std::string pattern = (parent / "synthetic-netko-XXXXXX").string();
        std::vector<char> tmp(pattern.begin(), pattern.end()); tmp.push_back(0);
        char* dir = mkdtemp(&tmp[0]);
        Require(dir != NULL, "mkdtemp failed");
        mapArgs["-datadir"] = dir;
        mapArgs["-printtoconsole"] = "1";
        fPrintToConsole = true;
        if (std::getenv("NETKO_TEST_DEBUG_CREATION")) {
            fDebug = true;
            mapMultiArgs["-debug"].push_back("creation");
        }
        SelectParams(CChainParams::MAIN); // uses rules only; no networking initialization
        SetMockTime(NOW + 3600);
        std::cout << "ISOLATED SYNTHETIC FIXTURE datadir=" << dir << " mode=" << mode << std::endl;
        LOCK(cs_main);
        CTxDB db("cr+");
        Fixture f(db);
        const bool patched = mode == "patched";
        WalletCase(db, f, 900000, 0, true, 25 * COIN);
        WalletCase(db, f, 900001, 0, patched, COIN / 4);
        WalletCase(db, f, 900001, CENT, true, (patched ? COIN / 4 : 0) + CENT);
        ConnectCase(db, f, "historical_boundary", 900000, 25 * COIN, 0, true);
        ConnectCase(db, f, "historical_overclaim", 900000, 25 * COIN + 1, 0, false);
        ConnectCase(db, f, "corrected_reward", 900001, COIN / 4, 0, patched);
        ConnectCase(db, f, "post_boundary_overclaim", 900001, COIN / 4 + 1, 0, false);
        ConnectCase(db, f, "legacy_zero_underclaim", 900001, 0, 0, true);
        ConnectCase(db, f, "legacy_fees_only", 900001, CENT, CENT, true);
        ConnectCase(db, f, "corrected_reward_plus_fees", 900001, COIN / 4 + CENT, CENT, patched);
        ConnectCase(db, f, "fees_overclaim", 900001, COIN / 4 + CENT + 1, CENT, false);
        pindexBest = NULL;
        db.Close();
        std::cout << "PASS 3 wallet trials (each successful stake connected) + 8 explicit full ConnectBlock trials; no node, peers, broadcast or live-chain replay" << std::endl;
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "FAIL: " << e.what() << std::endl;
        return 1;
    }
}
