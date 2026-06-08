# Doosan E0509 - ROBOTIS RH-P12-RN TCP Bridge

🚧 **Work In Progress**: 이 프로젝트는 현재 활발히 개발 및 개선 중이며, 지속적으로 커밋이 추가될 예정입니다. 🚧

Doosan E0509 로봇에서 <b>ROS 2 환경과 ROBOTIS RH-P12-RN 그리퍼 간의 양방향 제어(Read/Write)</b>를 구현하기 위한 TCP 통신 브리지 및 실시간 모니터링 대시보드 프로젝트입니다.

---

## 📌 Background & Motivation

* **The E0509 Limitation:** 두산 로봇의 다른 상위 모델에서는 DRL(Doosan Robot Language)과 ROS 2 간의 통신이 원활할 수 있으나, **최소한 E0509 모델 환경에서는** DRL을 통해 그리퍼에 명령(Write)을 내릴 수는 있어도, 그리퍼의 상태값(Read)을 다시 ROS 2로 피드백해주는 경로가 막혀 있는 문제가 발생했습니다.
* **The Solution:** 이를 해결하기 위해 DRL 내부에 **TCP Socket Client**를 직접 구현하여, 컨트롤러가 읽어온 그리퍼 데이터를 ROS 2(TCP Server)로 실시간 우회 전송하는 커스텀 브리지를 개발했습니다.

---

## 🚀 Key Features

* **Real-Time Web Dashboard (20 FPS):** `Flask`와 `SocketIO`를 활용하여 그리퍼의 현재 위치(Position), 힘(Current), 온도(Temperature) 및 구동 상태를 웹 브라우저에서 50ms 간격으로 실시간 모니터링하고 제어할 수 있습니다.
* **Smart Grasping Detection:** 단순히 위치에 도달했는지만 판단하는 것이 아니라, DRL 내부에서 **목표 전류의 90% 이상 도달 시 객체를 꽉 잡은 것(Grasping)으로 간주**하여 더욱 안정적인 파지 판별이 가능합니다.
* **Lightweight Binary Protocol:** `[MAGIC] [VERSION] [CMD] [SEQ] [PAYLOAD]` 형태의 자체적인 경량 구조체 패킷 프로토콜을 설계하여 데이터 송수신 딜레이를 최소화했습니다.

---

## 🛠 System Architecture

```text
[ Web Dashboard ] <--(SocketIO, 20Hz)--> [ ROS 2 (Python Node) ]
                                                |
                                          (TCP Socket)
                                                |
[ Doosan Controller (DRL) ] <--(Modbus RTU)--> [ RH-P12-RN Gripper ]
