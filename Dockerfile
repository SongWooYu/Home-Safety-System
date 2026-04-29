# 1. 라즈베리 파이 5 환경(Bookworm)과 일치하는 베이스 이미지
FROM debian:bookworm-slim

# 2. 저장소 추가를 위한 기본 도구 설치
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# 3. 라즈베리 파이 전용 저장소 키 및 리스트 추가 (중요: 이 과정이 없으면 libcamera를 못 찾습니다)
RUN mkdir -p /usr/share/keyrings && \
    wget -qO - https://archive.raspberrypi.org/debian/raspberrypi.gpg.key | gpg --dearmor -o /usr/share/keyrings/raspberrypi-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.gpg] http://archive.raspberrypi.org/debian/ bookworm main" > /etc/apt/sources.list.d/raspi.list

# 4. 이제 라즈베리 파이 전용 패키지를 포함하여 설치
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-libcamera \
    libcamera-v4l2 \
    libcamera-tools \
    python3-opencv \
    python3-flask \
    python3-numpy \
    gcc \
    libcap-dev \
    && rm -rf /var/lib/apt/lists/*

# 5. Picamera2 설치
RUN pip3 install picamera2 --break-system-packages

WORKDIR /workspace
CMD ["python3", "app.py"]