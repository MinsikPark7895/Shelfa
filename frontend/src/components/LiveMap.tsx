import React, { useEffect, useState } from 'react';
import mqtt from 'mqtt';
import './LiveMap.css';

interface Pose {
  x: number;
  y: number;
  yaw: number;
}

interface RobotStatus {
  status: string;
  message: string;
}

const LiveMap: React.FC = () => {
  const [pose, setPose] = useState<Pose | null>(null);
  const [robotStatus, setRobotStatus] = useState<RobotStatus | null>(null);

  useEffect(() => {
    // MQTT 연결 옵션 (GCP 클라우드 접속)
    const isSecure = window.location.protocol === 'https:';
    const options: mqtt.IClientOptions = {
      username: import.meta.env.VITE_MQTT_USER || '',
      password: import.meta.env.VITE_MQTT_PASSWORD || '',
      reconnectPeriod: 1000,
      protocol: isSecure ? 'wss' : 'ws',
    };

    const envUrl = import.meta.env.VITE_MQTT_BROKER_URL;
    const brokerUrl = envUrl
      ? envUrl
      : window.location.protocol === 'https:'
        ? 'wss://' + window.location.hostname + '/mqtt'
        : 'ws://localhost:9001';
    const client = mqtt.connect(brokerUrl, options);

    client.on('connect', () => {
      console.log('LiveMap: MQTT 웹소켓 연결 성공');
      client.subscribe('shelfa/robot/pose', (err) => {
        if (!err) console.log('LiveMap: shelfa/robot/pose 구독 완료');
      });
      client.subscribe('shelfa/robot/status', (err) => {
        if (!err) console.log('LiveMap: shelfa/robot/status 구독 완료');
      });
    });

    client.on('message', (topic, message) => {
      try {
        const data = JSON.parse(message.toString());
        if (topic === 'shelfa/robot/pose') setPose(data as Pose);
        if (topic === 'shelfa/robot/status') setRobotStatus(data as RobotStatus);
      } catch (e) {
        console.error('JSON 파싱 에러', e);
      }
    });

    return () => {
      if (client) {
        client.end();
      }
    };
  }, []);

  // library_map.yaml의 메타데이터 상수
  const resolution = 0.05;
  const originX = -23.3;
  const originY = -15.5;
  // 실제 지도 이미지 크기 (886 x 832)
  const mapWidth = 886;
  const mapHeight = 832;

  // 실제 물리 좌표 (Meters) -> 픽셀 좌표 (Pixels) 변환
  const getPixelPosition = () => {
    if (!pose) return { left: '-100px', top: '-100px', transform: 'rotate(0deg)' };

    // 픽셀 변환 로직
    const px = (pose.x - originX) / resolution;
    const py = mapHeight - ((pose.y - originY) / resolution);

    return {
      left: `${px}px`,
      top: `${py}px`,
      // 로봇 회전 (CSS rotate 적용을 위해)
      // ROS 좌표계는 반시계방향이 +, 웹 브라우저 CSS는 시계방향이 +
      transform: `translate(-50%, -50%) rotate(${-pose.yaw}deg)`,
    };
  };

  return (
    <div className="livemap-container">
      <div className="livemap-title-row">
        <h3>실시간 로봇 관제</h3>
        <div className={`livemap-status ${pose ? 'connected' : 'disconnected'}`}>
          {pose ? '로봇 연결됨' : '신호 대기중...'}
        </div>
      </div>
      <div className="livemap-wrapper">
        <img 
          src="/assets/library_map.png" 
          alt="도서관 지도" 
          className="livemap-image"
          style={{ width: `${mapWidth}px`, height: `${mapHeight}px` }} 
          onError={(e) => {
            (e.target as HTMLImageElement).src = '/assets/qr-placeholder.png'; // 이미지가 없을 경우 플레이스홀더
          }}
        />
        {/* 로봇 마커 */}
        <div 
          className="livemap-robot-marker"
          style={getPixelPosition()}
        >
          {/* 마커 내부 화살표 (바라보는 방향) */}
          <div className="livemap-robot-arrow"></div>
        </div>
      </div>
      {pose && (
        <div className="livemap-coordinates">
          현재 위치: X {pose.x.toFixed(2)}m, Y {pose.y.toFixed(2)}m (각도: {pose.yaw.toFixed(1)}°)
        </div>
      )}
      {robotStatus && (
        <div className={`livemap-robot-status ${robotStatus.status === 'SUCCESS' ? 'status-success' : 'status-error'}`}>
          {robotStatus.status === 'SUCCESS' ? '✅' : '❌'} {robotStatus.message}
        </div>
      )}
    </div>
  );
};

export default LiveMap;
