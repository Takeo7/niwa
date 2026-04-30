        # Niwa v1.1 Smoke Report

        **Result:** PASS
        **Date:** 2026-04-30T15:45:34.470677+00:00
        **Duration:** 4.9s
        **Sandbox:** `/tmp/niwa-smoke-plcnycjt`

        ## Checks

        | | Check | Duration | Error | Log |
        |---|---|---|---|---|
        | ✅ | health | 0.00s | ok | [log](.smoke/logs/health.log) |
| ✅ | project create | 0.03s | ok | [log](.smoke/logs/project_create.log) |
| ✅ | task execute/verify/finalize | 0.58s | ok | [log](.smoke/logs/task_execute_verify_finalize.log) |
| ✅ | static deploy | 0.01s | ok | [log](.smoke/logs/static_deploy.log) |
| ✅ | split triage | 2.13s | ok | [log](.smoke/logs/split_triage.log) |
| ✅ | waiting_input respond validation | 0.02s | ok | [log](.smoke/logs/waiting_input_respond_validation.log) |
| ✅ | attachments | 0.03s | ok | [log](.smoke/logs/attachments.log) |
| ✅ | fake PR (dangerous mode) | 1.05s | ok | [log](.smoke/logs/fake_PR_(dangerous_mode).log) |

        ## Environment

        | Key | Value |
        |---|---|
        | python | 3.11.15 |
| os | Linux |
| git | /usr/bin/git |
| node | /opt/node22/bin/node |
