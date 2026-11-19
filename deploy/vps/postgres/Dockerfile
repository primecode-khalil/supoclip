# syntax=docker/dockerfile:1.7

# Build the same privilege-drop helper shipped by the PostgreSQL base using a
# patched compiler. Keep module versions/checksums from the pinned upstream tree.
FROM --platform=$BUILDPLATFORM golang:1.27.4-alpine3.24@sha256:0a5f7fe796599ff487605987432e7619ae45beeb2fba4c2ce0b907879932aebf AS gosu-build
ARG TARGETARCH
WORKDIR /src
ADD --checksum=sha256:33d7537d588ea49458b9509bcf4554bdf5ceacc66da71e5caa1058ea3b689c3b \
    https://codeload.github.com/tianon/gosu/tar.gz/6456aaa0f3c854d199d0f037f068eb97515b7513 /tmp/gosu.tar.gz
RUN tar -xzf /tmp/gosu.tar.gz --strip-components=1 -C /src
RUN CGO_ENABLED=0 GOOS=linux GOARCH="$TARGETARCH" GOTOOLCHAIN=local \
    go build -mod=readonly -trimpath -buildvcs=false -o /out/gosu . \
    && go version -m /out/gosu

FROM postgres:15-alpine
COPY --from=gosu-build --chmod=0755 /out/gosu /usr/local/bin/gosu
COPY --from=gosu-build /src/LICENSE /usr/local/share/licenses/gosu/LICENSE
COPY --from=gosu-build /go/pkg/mod/github.com/moby/sys/user@v0.1.0/LICENSE /usr/local/share/licenses/gosu/moby-sys-user-LICENSE
COPY --from=gosu-build /go/pkg/mod/golang.org/x/sys@v0.1.0/LICENSE /usr/local/share/licenses/gosu/golang-x-sys-LICENSE
COPY --from=gosu-build /usr/local/go/LICENSE /usr/local/share/licenses/gosu/Go-LICENSE

# Exercise the replacement during the build without changing the server's
# entrypoint, UID, PGDATA, supported version, or initialization behavior.
RUN gosu --version && test "$(gosu postgres id -u)" = "$(id -u postgres)"
