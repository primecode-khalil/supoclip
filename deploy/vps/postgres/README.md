# PostgreSQL image compatibility patch

The runtime remains the official PostgreSQL 15 Alpine image. This Dockerfile
replaces only its `gosu` 1.19 privilege-drop executable with the **same source
version**, rebuilt using Go 1.27.4. PostgreSQL's entrypoint, server, extensions,
user and data-directory layout remain inherited from the base image.

The official base's `gosu --version` reports Go 1.24.6. The repository's final
image scan flags its standard-library build metadata for
[CVE-2025-68121 / GO-2026-4337](https://pkg.go.dev/vuln/GO-2026-4337).
[Upstream gosu's policy](https://github.com/tianon/gosu/blob/1.19/SECURITY.md)
explains that generic Go library findings can be unreachable in this helper.
This rebuild satisfies the repository's compiler-based image gate without
excluding a component or CVE, suppressing compiler/module build metadata, or
changing server versions.

## Pinned inputs and licenses

| Input | Pin |
| --- | --- |
| Compiler | `golang:1.27.4-alpine3.24`, multi-architecture index `sha256:0a5f7fe796599ff487605987432e7619ae45beeb2fba4c2ce0b907879932aebf` |
| gosu | [1.19 commit `6456aaa0f3c854d199d0f037f068eb97515b7513`](https://github.com/tianon/gosu/tree/6456aaa0f3c854d199d0f037f068eb97515b7513) |
| Source archive | SHA-256 `33d7537d588ea49458b9509bcf4554bdf5ceacc66da71e5caa1058ea3b689c3b` |
| Modules | Unmodified upstream `go.mod` / `go.sum`, with `-mod=readonly` |

[Go's official release feed](https://go.dev/dl/?mode=json) lists 1.27.4 as a
stable release. The builder image is pinned by its multi-architecture digest;
Go cross-compiles a static binary for the requested Linux AMD64 or ARM64 target.
The Go toolchain cannot silently download a different version (`GOTOOLCHAIN=local`).
Build information remains available to scanners (`go version -m`).

The image includes the upstream Apache-2.0 gosu license, its two module licenses,
and the Go runtime license under `/usr/local/share/licenses/gosu/`.

## Verification

```sh
docker build --pull -t supoclip-postgres:test deploy/vps/postgres
docker run --rm supoclip-postgres:test gosu --version
docker run --rm supoclip-postgres:test gosu postgres id
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:0.76.1 image --scanners vuln --severity CRITICAL \
  --ignore-unfixed --exit-code 1 --timeout 15m supoclip-postgres:test
```

Also verify a fresh database initialization and a retained-volume restart before
deploying changes to this image. A rebuild does not authorize a production
database restart with active work.

Verified on 16 November 2026:

- AMD64 and ARM64 image builds pass the embedded version and privilege-drop checks.
- Both final images pass the exact Trivy command above with zero fixable critical
  findings in Alpine packages and the replacement Go binary.
- The ARM64 image initializes a fresh database, runs the server as UID 70, and
  retains a SQL marker after a stopped container is recreated on its data volume.

Recheck the freshly pulled official base during maintenance. Remove this
override once that image passes the same gate, rather than carrying an older
helper over a future upstream helper update indefinitely.
