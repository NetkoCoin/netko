#!/usr/bin/env python3
"""Compile and test the production staking reward function in isolation.

Run: python3 contrib/test_stake_reward.py
Requires Python 3 and a C++11 compiler (CXX, default: c++). No node or wallet
is started. This checks reward arithmetic, not block validation or staking.
"""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def reward_source():
    source = (ROOT / "src/main.cpp").read_text()
    signature = re.search(
        r"^int64_t GetProofOfStakeReward\([^\n]*\)\s*\{", source, re.MULTILINE
    )
    if signature is None:
        raise RuntimeError("Cannot locate the production staking reward function")
    start = signature.end() - 1
    depth = 1
    end = start + 1
    while depth and end < len(source):
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    if depth:
        raise RuntimeError("Unterminated staking reward function")
    constants = (ROOT / "src/util.h").read_text()
    coin = re.search(r"^static const int64_t COIN\s*=\s*\d+;", constants, re.MULTILINE)
    if coin is None:
        raise RuntimeError("Cannot locate the production COIN constant")
    return coin.group(0) + "\n" + source[signature.start():end]


def main():
    harness = """#include <cstdint>
#include <iostream>
// Logging is not relevant to the reward calculation.
#define LogPrint(...) ((void)0)
""" + reward_source() + """
int main() {
    const int heights[] = {1, 899999, 900000, 900001, 900002, 1000000};
    const int64_t fees[] = {0, 1, 1000000};
    const int64_t ages[] = {0, 1, 365};
    int checks = 0;
    for (int height : heights) {
        for (int64_t fee : fees) {
            for (int64_t age : ages) {
                const int64_t subsidy = height <= 900000 ? 2500000000LL : 25000000LL;
                const int64_t expected = subsidy + fee;
                const int64_t actual = GetProofOfStakeReward(age, fee, height);
                if (actual != expected || actual <= 0) {
                    std::cerr << "FAIL height=" << height << " fee=" << fee
                              << " age=" << age << " expected=" << expected
                              << " actual=" << actual << '\\n';
                    return 1;
                }
                ++checks;
            }
        }
    }
    std::cout << "PASS: " << checks << " production reward checks\\n";
}
"""
    # Respect TMPDIR when set; temporary sources/binaries are removed afterwards.
    with tempfile.TemporaryDirectory(prefix="netko-stake-reward-") as directory:
        source = Path(directory) / "stake_reward.cpp"
        binary = Path(directory) / "stake_reward"
        source.write_text(harness)
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        subprocess.run(compiler + ["-std=c++11", str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
