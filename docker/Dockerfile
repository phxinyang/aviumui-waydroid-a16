# AOSP/LineageOS 16 构建环境(Ubuntu 24.04)
# 用 docker 隔离,不碰宿主 Arch 系统。
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# AOSP + LineageOS 构建依赖(Ubuntu 24.04/noble)
RUN apt-get update && apt-get install -y --no-install-recommends \
    bc \
    bison \
    build-essential \
    ccache \
    curl \
    flex \
    g++-multilib \
    gcc-multilib \
    git \
    gnupg \
    gperf \
    imagemagick \
    lib32ncurses6 \
    lib32readline-dev \
    lib32z1-dev \
    libc6-dev-i386 \
    libgl1-mesa-dev \
    liblz4-tool \
    libncurses-dev \
    libsdl1.2-dev \
    libssl-dev \
    libx11-dev \
    libxml2 \
    libxml2-utils \
    lzop \
    meson \
    ninja-build \
    openjdk-17-jdk \
    pngcrush \
    python3 \
    python3-pip \
    python3-requests \
    rsync \
    schedtool \
    squashfs-tools \
    unzip \
    x11proto-core-dev \
    xsltproc \
    zip \
    zlib1g-dev \
    fontconfig \
    git-lfs \
    glslang-tools \
    python3-mako \
    python3-packaging \
    python3-pycparser \
    python3-yaml \
    && rm -rf /var/lib/apt/lists/*

# git-lfs 全局启用(LineageOS 的 chromium-webview 预编译仓库用 LFS)
RUN git lfs install

# mesa3d 构建需要 meson>=1.4 (Ubuntu 24.04 自带 1.3.2), 用 pip 装新版
RUN pip3 install --break-system-packages meson==1.7.2

# git am 需要身份,否则所有补丁都会报 "Committer identity unknown"
RUN git config --global user.email "build@avium.local" \
 && git config --global user.name "Avium Build"

# repo 工具
RUN curl -sSL https://storage.googleapis.com/git-repo-downloads/repo \
        -o /usr/local/bin/repo \
    && chmod +x /usr/local/bin/repo

# 构建工作区
RUN mkdir -p /build && chmod 777 /build
WORKDIR /build
