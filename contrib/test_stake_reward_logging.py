#!/usr/bin/env python3
"""Check the production reward log format using the real tinyformat header.

Run: python3 contrib/test_stake_reward_logging.py
Requires Python 3 and a C++11 compiler. No node, wallet or legacy libraries.
FormatMoney is a fixture formatter; this tests argument matching and height
logging, not production money formatting or native log-category selection.
"""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from test_stake_reward import ROOT, reward_source


def main():
    harness = """#include <cstdint>
#include <iostream>
#include <string>
#include "tinyformat.h"
static std::string message;
static std::string FormatMoney(int64_t amount) { return std::to_string(amount); }
template<typename... Args>
static void LogPrint(const char*, const char* format, const Args&... args) {
    message = tfm::format(format, args...);
}
""" + reward_source() + """
int main() {
    try {
        for (int height : {900000, 900001}) {
            GetProofOfStakeReward(1000, 0, height);
            const std::string expected = "nCoinAge=1000 nHeight=" + std::to_string(height);
            if (message.find(expected) == std::string::npos) {
                std::cerr << "FAIL: missing reward log context: " << message;
                return 1;
            }
        }
        std::cout << "PASS: 2 production reward logging checks\\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\\n';
        return 1;
    }
}
"""
    with tempfile.TemporaryDirectory(prefix="netko-stake-logging-") as directory:
        source = Path(directory) / "stake_logging.cpp"
        binary = Path(directory) / "stake_logging"
        source.write_text(harness)
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        subprocess.run(compiler + ["-std=c++11", "-I", str(ROOT / "src"), str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
