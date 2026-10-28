# Empower Web API calls used (via opti-hplc-handler)

| Purpose | Call |
|---|---|
| Log in (token) | `POST /authentication/login` {service, userName, password, project} |
| Instrument methods, method sets, sample set methods | `GET /project/methods?methodTypes=...` |
| Plate types | `GET /configuration/plate-types-list` |
| Create a sample set method | `POST /project/methods/sample-set-method[?auditTrailComment=...]` |
| Run it | `POST /acquisition/run-sample-set-method` {sampleSetMethodName, sampleSetName, nodeName, systemName, runMode, ...} |
| Nodes and systems | `GET /acquisition/nodes`, `GET /acquisition/chromatographic-systems?nodeName=` |
| System status | `GET /acquisition/chromatographic-system-status?nodeName=&systemName=` |
| Log out | `DELETE` on the session |

Each injection becomes an "Inject Samples" line with Empower fields SampleName, Vial, InjVol
and MethodSetOrReportMethod; a sample with injections: 3 becomes three lines. Results retrieval through the Web API is not covered
here; use an export method and `export_dir`.
