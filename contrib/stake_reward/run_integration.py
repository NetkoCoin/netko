#!/usr/bin/env python3
"""Link real daemon objects into an isolated production-height regression.

Only a new external build directory is written. No node or wallet is started.
See README.md for prerequisites and the synthetic-ancestry verification limit.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

BASELINE = "69d813fea6e3865b9d2622108c74d5f67dc27343"
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=HERE.parents[1] / "src")
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--baseline-ref", default=BASELINE)
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--deps-prefix", type=Path, default=os.environ.get("NETKO_DEPS"))
    parser.add_argument("--openssl-prefix", type=Path, default=os.environ.get("NETKO_SSL"))
    args = parser.parse_args()
    src = args.source_dir.resolve(strict=True)
    out = args.build_dir.resolve()
    if out == src.parent or src.parent in out.parents:
        parser.error("--build-dir must be outside the source checkout")
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    runs = out / "runs"
    runs.mkdir(mode=0o700)
    baseline = (args.baseline_source.read_bytes() if args.baseline_source else
                subprocess.check_output(["git", "-C", str(src.parent), "show", args.baseline_ref + ":src/main.cpp"]))
    (out / "main-baseline.cpp").write_bytes(baseline)
    compiler = shlex.split(os.environ.get("CXX", "g++"))
    flags = ["-std=gnu++11", "-O2", "-pthread", "-ffunction-sections", "-fdata-sections",
             "-DENABLE_WALLET", "-DBOOST_SPIRIT_THREADSAFE"]
    includes = [src, src / "obj", src / "leveldb/include", src / "leveldb/helpers"]
    libs = []
    for prefix, library in ((args.deps_prefix, "lib/x86_64-linux-gnu"), (args.openssl_prefix, "lib")):
        if prefix:
            prefix = prefix.resolve(strict=True)
            includes.append(prefix / "include")
            libs += ["-L" + str(prefix / library), "-Wl,-rpath," + str(prefix / library)]
    flags += ["-I" + str(path) for path in includes]
    libs += ["-Wl,--gc-sections", "-Wl,-z,noexecstack", "-lrt", "-lboost_chrono", "-lboost_timer",
             "-lboost_system", "-lboost_filesystem", "-lboost_program_options", "-lboost_thread",
             "-ldb_cxx", "-lssl", "-lcrypto", str(src / "leveldb/libleveldb.a"),
             str(src / "leveldb/libmemenv.a"), "-lz", "-ldl", "-lpthread"]
    # Use a clean full-wallet daemon build. Exclude separately built comparison
    # mains so a prior local test cannot silently select a different revision.
    objects = [path for path in sorted((src / "obj").glob("*.o"))
               if path.name not in ("bitcoind.o", "main.o", "main-baseline.o")]
    if not objects or not (src / "obj/wallet.o").is_file() or not (src / "obj/main.o").is_file():
        parser.error("build wallet-enabled daemon objects before running this test")
    commands = [compiler + flags + ["-c", str(HERE / "connectblock_regression.cpp"), "-o", str(out / "harness.o")],
                compiler + flags + ["-c", str(out / "main-baseline.cpp"), "-o", str(out / "main-baseline.o")]]
    for revision, main_object in (("patched", src / "obj/main.o"), ("baseline", out / "main-baseline.o")):
        commands.append(compiler + ["-o", str(out / ("harness-" + revision)), str(out / "harness.o"), str(main_object)]
                        + [str(path) for path in objects] + libs)
    (out / "build-commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    with (out / "build.log").open("w") as log:
        for command in commands:
            subprocess.run(command, cwd=src, stdout=log, stderr=subprocess.STDOUT, timeout=180, check=True)
    env = os.environ.copy()
    env.pop("NETKO_TEST_DEBUG_CREATION", None)
    trials = [("baseline", "baseline", False, 0), ("patched", "patched", False, 0),
              ("baseline", "patched", False, 1), ("patched", "patched", True, 0)]
    results = []
    for number, (binary, mode, debug, expected_exit) in enumerate(trials):
        trial_env = dict(env)
        if debug:
            trial_env["NETKO_TEST_DEBUG_CREATION"] = "1"
        result = subprocess.run([str(out / ("harness-" + binary)), mode, str(runs)],
                                env=trial_env, capture_output=True, text=True, timeout=90)
        log = result.stdout + result.stderr
        (out / ("trial-%d.log" % number)).write_text(log)
        if result.returncode != expected_exit:
            raise RuntimeError("unexpected test exit; see trial-%d.log" % number)
        if expected_exit:
            if ("WALLET height=900000 fee=0 created=1 expected=1" not in log or
                    "WALLET height=900001 fee=0 created=0 expected=1" not in log or
                    "FAIL: CreateCoinStake result mismatch" not in log):
                raise RuntimeError("baseline negative control failed for an unexpected reason")
        elif (sum(line.startswith("WALLET ") for line in log.splitlines()) != 3 or
              sum(line.startswith("CASE ") for line in log.splitlines()) != 8 or
              "PASS 3 wallet trials" not in log):
            raise RuntimeError("missing full integration trial results")
        results.append({"binary": binary, "expectations": mode, "creation_logging": debug,
                        "exit": result.returncode, "expected_exit": expected_exit})
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (src / "main.cpp", src / "chainparams.cpp", HERE / "connectblock_regression.cpp", out / "main-baseline.cpp")}
    (out / "results.json").write_text(json.dumps({"trials": results, "source_sha256": hashes,
        "scope": "production-height synthetic ancestry, not full history or network replay"}, indent=2) + "\n")
    print("PASS: baseline + patched + expected red control + creation logging integration")
    print("Evidence:", out)


if __name__ == "__main__":
    main()
