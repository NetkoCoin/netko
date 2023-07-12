// Copyright (c) 2009-2012 The Bitcoin developers
// Distributed under the MIT/X11 software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <boost/assign/list_of.hpp> // for 'map_list_of()'
#include <boost/foreach.hpp>

#include "checkpoints.h"

#include "txdb.h"
#include "main.h"
#include "uint256.h"


static const int nCheckpointSpan = 500;

namespace Checkpoints
{
    typedef std::map<int, uint256> MapCheckpoints;

    //
    // What makes a good checkpoint block?
    // + Is surrounded by blocks with reasonable timestamps
    //   (no blocks before with a timestamp after, none after with
    //    timestamp before)
    // + Contains no strange transactions
    //
    static MapCheckpoints mapCheckpoints =
        boost::assign::map_list_of
        ( 0,   uint256("0x00000b1677bc31fdf9d92f0781896022289464b4a31a3576a486390b86ace531") ) // genesis
        ( 50000,   uint256("0xf9c0721cbf01b5c1579a2538cc469c3fc212d3d4c11794542fb53ab4f6b6048e") )
        ( 100000,   uint256("0xa304cc0b47360c511e31aaf3499e6d20bb94038c6976096c8e8e2768bdb80a3b") )
        ( 150000,   uint256("0x9670f10c225211a838aefab6ba079fcdcd32dcb3425c4cf85b0fed43b566d8fc") )
        ( 200000,   uint256("0xa8d150e4026c00e3b720f34f7dd6956f78bfd9db42d26330871098d8ff275213") )
        ( 240000,   uint256("0x4f36341a6d8f8c7fd313d8f8c01523a0bca9ad614f1123ce59024b45a339befe") )
        ( 278000,   uint256("0x6899ae0197f0552dc86ec55413eaf59905e3d9c695279860827464ddd0658bef") )
        ( 296756,   uint256("0x151cf67b473236b0b5c7422c967a0555cd2827a707745840badf4498d5e3e369") )
        ( 309668,   uint256("0x71896e216eaf74512ed3b5403a4db32dc51fb94dd6bb2414ab41ca81859f96e6") )
        ( 318823,   uint256("0xce22b29442d7d4e701967fcace3d707cd1e67f2624e74195131ea697c4abd52a") )
        ( 336636,   uint256("0xe57af6f99d9d22a5a96211790af7329855328d8b0521c95a99c3ea41116b8868") )
        ( 341111,   uint256("0x5a7e7f416037a7afadf091191c0940756a742de0dc18fd26207f56a6fb8ae13c") )
        ( 371144,   uint256("0xa5276315015a7240e549849028be3cbf5554610128f5ff5e803e02e9c945ab71") )
        ( 416918,   uint256("0xd65962e793ef8c446147f2a4b0581e60c6fe7cdbe5233f7e22609feafafd1215") )
        ( 441775,   uint256("0x5b4444671231800a4c773d850396b073e7eef2dbab33681677ecffefb71f6a41") )
        ( 477829,   uint256("0x07b2d4ca094ddf584ff98bae028129cf6f6dc9f2697314e334d4b6be31df385e") )
        ( 563360,   uint256("0xb4f86f102a3762d0c191e2e338684fe82c35a733a8ace65f5b2d5b8eca299030") )
        ( 585856,   uint256("0x3a5ed4262d04d1a40c78a0ea106934c810f836ab7e6c959c75e299ab0d2eba39") )
        
    ;

    // TestNet has no checkpoints
    static MapCheckpoints mapCheckpointsTestnet;

    bool CheckHardened(int nHeight, const uint256& hash)
    {
        MapCheckpoints& checkpoints = (TestNet() ? mapCheckpointsTestnet : mapCheckpoints);

        MapCheckpoints::const_iterator i = checkpoints.find(nHeight);
        if (i == checkpoints.end()) return true;
        return hash == i->second;
    }

    int GetTotalBlocksEstimate()
    {
        MapCheckpoints& checkpoints = (TestNet() ? mapCheckpointsTestnet : mapCheckpoints);

        if (checkpoints.empty())
            return 0;
        return checkpoints.rbegin()->first;
    }

    CBlockIndex* GetLastCheckpoint(const std::map<uint256, CBlockIndex*>& mapBlockIndex)
    {
        MapCheckpoints& checkpoints = (TestNet() ? mapCheckpointsTestnet : mapCheckpoints);

        BOOST_REVERSE_FOREACH(const MapCheckpoints::value_type& i, checkpoints)
        {
            const uint256& hash = i.second;
            std::map<uint256, CBlockIndex*>::const_iterator t = mapBlockIndex.find(hash);
            if (t != mapBlockIndex.end())
                return t->second;
        }
        return NULL;
    }

    // Automatically select a suitable sync-checkpoint
    const CBlockIndex* AutoSelectSyncCheckpoint()
    {
        const CBlockIndex *pindex = pindexBest;
        // Search backward for a block within max span and maturity window
        while (pindex->pprev && pindex->nHeight + nCheckpointSpan > pindexBest->nHeight)
            pindex = pindex->pprev;
        return pindex;
    }

    // Check against synchronized checkpoint
    bool CheckSync(int nHeight)
    {
        const CBlockIndex* pindexSync = AutoSelectSyncCheckpoint();

        if (nHeight <= pindexSync->nHeight)
            return false;
        return true;
    }
}
