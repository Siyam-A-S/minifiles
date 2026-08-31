# MiniFiles data-plane: userspace NFSv4 server (NFS-Ganesha, VFS FSAL).
# Userspace because kernel knfsd inside kind/CI containers is unreliable
# (module availability, overlayfs export restrictions) and needs privileged
# pods; Ganesha needs neither.
FROM debian:stable-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends nfs-ganesha nfs-ganesha-vfs \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /exports /var/run/ganesha
COPY ganesha.conf /etc/ganesha/ganesha.conf
EXPOSE 2049
CMD ["ganesha.nfsd", "-F", "-L", "/dev/stderr", "-f", "/etc/ganesha/ganesha.conf"]
