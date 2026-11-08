# beets + singles pipeline for TrueNAS. Build context = repository root:
#   docker build -f docker/Dockerfile -t ghcr.io/mess023/beets-me:test .
FROM python:3.13-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BEETSDIR=/config \
    PUID=1000 \
    PGID=1000

# ffmpeg: convert + replaygain (ebur128); fpcalc: chroma/AcoustID; gosu: drop root.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg libchromaprint-tools gosu curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY . /src
RUN pip install \
        "/src[web,autobpm,chroma,discogs,fetchart,embedart,lyrics,lastgenre,scrub]" \
        pyyaml \
    # external metadata sources; the constraint keeps *this* beets installed
    && pip freeze | grep -i '^beets==' > /tmp/constraints.txt \
    && pip install -c /tmp/constraints.txt beetcamp beets-beatport4 \
    # essentia: key detection (edma profile); optional, librosa fallback in code
    && (pip install -c /tmp/constraints.txt "essentia==2.1b6.dev1389" \
        || echo "essentia skipped: librosa key fallback will be used") \
    && rm -rf /src/.git

COPY docker/to-aiff /usr/local/bin/to-aiff
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/config.default.yaml /defaults/config.yaml
RUN chmod +x /usr/local/bin/to-aiff /entrypoint.sh

VOLUME ["/config", "/music/inbox", "/music/library"]
EXPOSE 8337
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD curl -fs http://localhost:8337/stats || exit 1

ENTRYPOINT ["tini", "--", "/entrypoint.sh"]
CMD ["web"]
