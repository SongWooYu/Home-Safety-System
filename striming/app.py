from flask import Flask, Response, render_template
from camera1 import VideoCamera, generate_frames

app = Flask(__name__)

# 카메라 객체 초기화 (전역으로 관리하여 리소스 낭비 방지)
video_camera = VideoCamera()

@app.route('/')
def index():
    """메인 페이지"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """비디오 스트리밍 API"""
    return Response(generate_frames(video_camera),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    # 호스트 0.0.0.0은 외부 접속 허용을 의미합니다.
    app.run(host='0.0.0.0', port=5000, threaded=True)