FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/srv/agent

WORKDIR /srv/agent

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping traceroute \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

RUN groupadd --gid 1000 pinger \
    && useradd --uid 1000 --gid pinger --shell /bin/sh pinger

COPY . .

# Bake git hash into the image (passed as build arg)
ARG GIT_HASH=unknown
RUN echo "${GIT_HASH}" > /srv/agent/VERSION

RUN chown -R pinger:pinger /srv/agent

# setcap so ping/traceroute work as non-root
RUN setcap cap_net_raw+ep /usr/bin/ping || true \
    && setcap cap_net_raw+ep /usr/bin/traceroute || true

USER pinger

CMD ["python", "-m", "agent.main"]
