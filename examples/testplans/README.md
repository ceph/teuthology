# Sample testplans

Draft plans modeled on what was scheduled in paddles in October 2026, mostly
against ceph `main`. Design stage only: not committed, and not yet in
ceph.git.

## Design choices

- Plans say only what to test. Build, lab and scheduling options (`-c`, `-m`,
  `-p`, `--force-priority`, `-f`, `-k`) come from the command line, so the
  scheduler (Jenkins, or a person) passes them. Each plan's description says
  which flags it expects.
- No partial plans: something that schedules part of a set, like the nightly
  rotation, uses a separate plan for each part.
- Runs that only differ by a command-line option reuse the same plan, e.g.
  `nightly-rados` with and without `-f debug`. Run names include the flavor
  and kernel, so the runs don't collide.
- Plan names don't name a branch. Each ceph branch would carry its own
  `qa/testplans/`, with subset sizes suited to that branch.
- `subset: random/M` picks a different piece each time a plan is scheduled,
  so repeated runs cover more of the suite. The piece used is logged and
  recorded in each job. A fixed `N/M` is for when runs must be comparable.

## Nightly runs (jenkins-build)

The `teuthology-nightly-cadence` job in ceph-build.git
(`teuthology-nightly-cadence/build/Jenkinsfile`) schedules these as the
`jenkins-build` user, on `trial`. It replaced the `teuthology` user's runs
from `qa/crontab/teuthology-cronjobs`, which stopped in December 2025. Every
day at about 06:00 UTC it takes the newest sha1 Shaman has built and
schedules `smoke` plus one entry from an 11-entry list, chosen by
`days since 1970 % 11`.

| Slot | Plan | Flags |
|---|---|---|
| (every day) | `smoke` | `-p 100 --force-priority` |
| 0 | `nightly-rados` | `-p 101 --force-priority` |
| 1 | `nightly-rados` | `-p 101 --force-priority -f debug` |
| 2 | `nightly-orch` | `-p 200` |
| 3 | `nightly-rbd` | `-p 200` |
| 4 | `nightly-fs` | `-p 200` |
| 5 | `nightly-powercycle` | `-p 200` |
| 6 | `nightly-rgw` | `-p 150` |
| 7 | `nightly-krbd` | `-p 200 -k testing` |
| 8 | `nightly-upgrade` | `-p 200` |
| 9 | `nightly-crimson-rados` | `-p 101 --force-priority -f debug` |
| 10 | `nightly-crimson-rados` | `-p 101 --force-priority` |

For example, slot 1 tests the same build as that day's smoke run:

    teuthology-testplan run -c main -S <sha1> -m trial -p 100 --force-priority smoke
    teuthology-testplan run -c main -S <sha1> -m trial -p 101 --force-priority -f debug nightly-rados

`weekly` bundles every default-flavor suite in the rotation into one plan,
for running the whole set against one build.

## Other recurring patterns

| Plan | Modeled on | Flags |
|---|---|---|
| `integration` | `pdonnell`'s `wip-pdonnell-testing-*` batches: the same suites and subset sizes each time, with a random piece of each | `smoke` alongside; `nightly-krbd` with `-k testing` |
| `release` | `yuriw`'s `umbrella-release` validation: one shared piece (`111/120000`) of every major suite | `nightly-krbd` with `-k testing`; client upgrade suites separately |
| `crimson-debug` | `shraddhaag`'s repeated crimson runs | `-f debug` |
| `nfs` | `pdonnell`'s repeated `fs:nfs` + `orch:cephadm:nfs` checks | `smoke` alongside |

Job counts from `show` match the real runs: for example, `release` against
the umbrella commit `yuriw` tested gives 318 rados, 211 orch and 190 rbd jobs,
as the real run did.

`release` checks a plan against the branch it's for: its suites come from
the umbrella branch, so validate it with an umbrella checkout.

## Known gaps and findings

- **A run can't unset a default.** `release` sets `subset` in `defaults`, so
  the runs that want the whole suite (crimson-rados, perf-basic) say
  `subset: 0/1`.
- **One plan can't use more than one suite branch.** Release validation also
  runs `upgrade-clients:client-upgrade-{squid,tentacle}-umbrella` with
  `--suite-branch squid` and `tentacle`, because those suites live on the
  older branches.
- **Required flags aren't checked.** `nightly-krbd` needs `-k testing` and
  `crimson-debug` needs `-f debug`, but only their descriptions say so.
- **`orch:cephadm:nfs` is a symlink to `fs/nfs`.** Scheduling both, as the
  real runs do, runs the same suite twice under two names. `nfs` keeps both
  to match.
- **The debug rados nightly slot schedules nothing.** In jenkins-build's
  history (October–November 2026), main has no debug-flavor `rados` run:
  slot 1 produced only `smoke`. Cause not yet investigated.

## Checking them

    teuthology-testplan validate --suite-dir <ceph.git checkout> --strict examples/testplans/*.yaml

`release` needs a checkout of the umbrella branch; the rest were checked
against `main`.
