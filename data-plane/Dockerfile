# NFS-godzilla: the MiniFiles data-plane image — a userspace NFSv4 server
# built on nfs-ganesha (VFS FSAL). Userspace because kernel knfsd inside
# kind/CI containers is unreliable (module availability, overlayfs export
# restrictions) and needs privileged pods; a userspace server needs neither.
FROM debian:stable-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends nfs-ganesha nfs-ganesha-vfs \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /exports /var/run/ganesha \
    # The VFS FSAL enumerates filesystems via setmntent(/etc/mtab); the
    # symlink normally created by systemd doesn't exist in containers, and
    # without it every export fails to create (server runs export-less).
    && ln -sf /proc/self/mounts /etc/mtab
COPY godzilla.conf /etc/ganesha/ganesha.conf
EXPOSE 2049
CMD ["ganesha.nfsd", "-F", "-L", "/dev/stderr", "-f", "/etc/ganesha/ganesha.conf"]
