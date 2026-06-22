#!/usr/bin/env python3
"""Service server wrapper for shelf pick and storage place missions."""

import json
import subprocess
from datetime import datetime
from pathlib import Path

import rclpy
from rclpy.node import Node
from shelfa_msgs.srv import PickBookFromShelf, PlaceBookInStorage


SHELF_MARKER_IDS = (0, 1)
STORAGE_MARKER_IDS = (2, 3)


class BookMissionServiceServer(Node):
    def __init__(self):
        super().__init__("book_mission_service_server")
        self.declare_parameter("dry_run", True)
        self.declare_parameter("dry_run_contract_mode", True)
        self.declare_parameter("auto_run", True)
        self.declare_parameter("state_json", "realtime_results/book_service_state.json")
        self.declare_parameter("mission_result_json", "realtime_results/mission_result.json")
        self.declare_parameter("pick_timeout_sec", 1200.0)
        self.declare_parameter("place_timeout_sec", 900.0)
        self.declare_parameter("service_pick_name", "/shelfa/pick_book_from_shelf")
        self.declare_parameter("service_place_name", "/shelfa/place_book_in_storage")
        self.declare_parameter("alignment_timeout_sec", 600.0)
        self.declare_parameter("marker2_alignment_timeout_sec", 600.0)
        self.declare_parameter("service_call_timeout_sec", 120.0)

        self.dry_run = bool(self.get_parameter("dry_run").value)
        self.dry_run_contract_mode = bool(
            self.get_parameter("dry_run_contract_mode").value
        )
        self.auto_run = bool(self.get_parameter("auto_run").value)
        self.state_json = Path(str(self.get_parameter("state_json").value))
        self.mission_result_json = str(self.get_parameter("mission_result_json").value)
        self.pick_timeout_sec = float(self.get_parameter("pick_timeout_sec").value)
        self.place_timeout_sec = float(self.get_parameter("place_timeout_sec").value)
        self.alignment_timeout_sec = float(self.get_parameter("alignment_timeout_sec").value)
        self.marker2_alignment_timeout_sec = float(
            self.get_parameter("marker2_alignment_timeout_sec").value
        )
        self.service_call_timeout_sec = float(
            self.get_parameter("service_call_timeout_sec").value
        )
        self.busy = False
        self.state = self.load_state()

        self.create_service(
            PickBookFromShelf,
            str(self.get_parameter("service_pick_name").value),
            self.handle_pick_book,
        )
        self.create_service(
            PlaceBookInStorage,
            str(self.get_parameter("service_place_name").value),
            self.handle_place_book,
        )
        self.get_logger().info(
            "Book mission service server ready: "
            f"dry_run={self.dry_run}, "
            f"dry_run_contract_mode={self.dry_run_contract_mode}, "
            f"auto_run={self.auto_run}, "
            f"state_json={self.state_json}"
        )

    def default_state(self):
        return {
            "held_book_title": "",
            "held_from_shelf_id": -1,
            "last_pick_result_json": "",
            "last_place_result_json": "",
            "updated_at": datetime.now().isoformat(),
        }

    def load_state(self):
        if not self.state_json.exists():
            return self.default_state()
        try:
            with open(self.state_json, "r", encoding="utf-8") as stream:
                state = json.load(stream)
            base = self.default_state()
            base.update(state)
            return base
        except Exception as exc:
            self.get_logger().warn(
                f"Failed to load service state; starting empty: {type(exc).__name__}: {exc}"
            )
            return self.default_state()

    def save_state(self):
        self.state["updated_at"] = datetime.now().isoformat()
        self.state_json.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_json, "w", encoding="utf-8") as stream:
            json.dump(self.state, stream, ensure_ascii=False, indent=2)

    def mission_common_args(self):
        return [
            "-p",
            f"dry_run:={'true' if self.dry_run else 'false'}",
            "-p",
            f"auto_run:={'true' if self.auto_run else 'false'}",
            "-p",
            f"result_json:={self.mission_result_json}",
            "-p",
            f"alignment_timeout_sec:={self.alignment_timeout_sec}",
            "-p",
            f"marker2_alignment_timeout_sec:={self.marker2_alignment_timeout_sec}",
            "-p",
            f"service_call_timeout_sec:={self.service_call_timeout_sec}",
        ]

    def clear_mission_status(self):
        path = Path(self.mission_result_json)
        if path.exists():
            path.unlink()

    def write_mission_status(self, result):
        path = Path(self.mission_result_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)

    def should_short_circuit_dry_run(self):
        return bool(self.dry_run and self.dry_run_contract_mode)

    def dry_run_pick_success(self, shelf_id, book_title):
        result = {
            "timestamp": datetime.now().isoformat(),
            "mode": "book_mission_service_server",
            "status": "experimental_pick_cycles_temp_placed",
            "dry_run_contract_mode": True,
            "request": {
                "service": "PickBookFromShelf",
                "shelf_id": int(shelf_id),
                "book_title": str(book_title),
            },
            "message": (
                "dry_run_contract_mode=true: 하위 정렬/비전/로봇 미션을 실행하지 않고 "
                "서비스 계약과 상태 전이만 검증했습니다."
            ),
        }
        self.write_mission_status(result)

    def dry_run_place_success(self, storage_id, held_title):
        result = {
            "timestamp": datetime.now().isoformat(),
            "mode": "book_mission_service_server",
            "status": "storage_marker_aligned_regripped_marker2_placed",
            "dry_run_contract_mode": True,
            "request": {
                "service": "PlaceBookInStorage",
                "storage_id": int(storage_id),
                "held_book_title": str(held_title),
            },
            "message": (
                "dry_run_contract_mode=true: 하위 정렬/재집기/넣기 미션을 실행하지 않고 "
                "서비스 계약과 상태 전이만 검증했습니다."
            ),
        }
        self.write_mission_status(result)

    def run_command(self, command, timeout_sec):
        self.get_logger().info("Running mission command:")
        self.get_logger().info("  " + " ".join(command))
        self.clear_mission_status()
        completed = subprocess.run(
            command,
            check=False,
            timeout=float(timeout_sec),
        )
        return int(completed.returncode)

    def read_mission_status(self):
        path = Path(self.mission_result_json)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as stream:
                return json.load(stream)
        except Exception as exc:
            return {
                "status": "result_json_read_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def reject_if_busy(self, response):
        if not self.busy:
            return False
        response.success = False
        response.message = "다른 책 미션이 실행 중입니다."
        response.result_json = self.mission_result_json
        return True

    def handle_pick_book(self, request, response):
        if self.reject_if_busy(response):
            response.held_book_title = self.state.get("held_book_title", "")
            return response
        shelf_id = int(request.shelf_id)
        book_title = str(request.book_title).strip()
        if shelf_id not in SHELF_MARKER_IDS:
            response.success = False
            response.message = "책장 번호는 0 또는 1이어야 합니다."
            response.held_book_title = self.state.get("held_book_title", "")
            response.result_json = self.mission_result_json
            return response
        if not book_title:
            response.success = False
            response.message = "책 제목이 비어 있습니다."
            response.held_book_title = self.state.get("held_book_title", "")
            response.result_json = self.mission_result_json
            return response
        if self.state.get("held_book_title"):
            response.success = False
            response.message = (
                "이미 뽑아둔 책이 있어 추가로 뽑을 수 없습니다: "
                f"{self.state.get('held_book_title')}"
            )
            response.held_book_title = self.state.get("held_book_title", "")
            response.result_json = self.mission_result_json
            return response

        if self.should_short_circuit_dry_run():
            self.dry_run_pick_success(shelf_id, book_title)
            self.state["held_book_title"] = book_title
            self.state["held_from_shelf_id"] = shelf_id
            self.state["last_pick_result_json"] = self.mission_result_json
            self.save_state()
            response.success = True
            response.message = (
                "dry_run 계약 테스트 완료: 하위 정렬/비전/로봇 미션은 실행하지 않고 "
                "책 뽑기 요청과 상태 저장만 검증했습니다."
            )
            response.held_book_title = self.state.get("held_book_title", "")
            response.result_json = self.mission_result_json
            return response

        command = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            "book_mission_state_machine",
            "--ros-args",
            *self.mission_common_args(),
            "-p",
            f"alignment_target_marker_id:={shelf_id}",
            "-p",
            f"target_title:={book_title}",
            "-p",
            f"alignment_dry_run:={'true' if self.dry_run else 'false'}",
            "-p",
            f"alignment_auto_run:={'true' if self.auto_run else 'false'}",
            "-p",
            "stop_after_experimental_pick_cycles:=true",
            "-p",
            "place_after_experimental_pick_cycles:=true",
            "-p",
            "marker2_alignment_enabled:=false",
        ]

        self.busy = True
        try:
            returncode = self.run_command(command, self.pick_timeout_sec)
            result = self.read_mission_status() or {}
            status = str(result.get("status", ""))
            success = returncode == 0 and status == "experimental_pick_cycles_temp_placed"
            response.success = bool(success)
            response.result_json = self.mission_result_json
            if success:
                self.state["held_book_title"] = book_title
                self.state["held_from_shelf_id"] = shelf_id
                self.state["last_pick_result_json"] = self.mission_result_json
                self.save_state()
                response.message = "책장에서 책을 뽑아 임시 위치에 내려놓았습니다."
            else:
                response.message = (
                    f"책 뽑기 실패: returncode={returncode}, status={status}, "
                    f"abort_reason={result.get('abort_reason')}"
                )
            response.held_book_title = self.state.get("held_book_title", "")
            return response
        except subprocess.TimeoutExpired:
            response.success = False
            response.message = "책 뽑기 미션이 시간 초과되었습니다."
            response.held_book_title = self.state.get("held_book_title", "")
            response.result_json = self.mission_result_json
            return response
        finally:
            self.busy = False

    def handle_place_book(self, request, response):
        if self.reject_if_busy(response):
            response.placed_book_title = ""
            return response
        storage_id = int(request.storage_id)
        held_title = str(self.state.get("held_book_title", ""))
        if storage_id not in STORAGE_MARKER_IDS:
            response.success = False
            response.message = "보관함 번호는 2 또는 3이어야 합니다."
            response.placed_book_title = ""
            response.result_json = self.mission_result_json
            return response
        if not held_title:
            response.success = False
            response.message = "뽑아둔 책이 없어 보관함에 넣을 수 없습니다."
            response.placed_book_title = ""
            response.result_json = self.mission_result_json
            return response

        if self.should_short_circuit_dry_run():
            self.dry_run_place_success(storage_id, held_title)
            response.success = True
            response.message = (
                "dry_run 계약 테스트 완료: 하위 정렬/재집기/넣기 미션은 실행하지 않고 "
                "보관함 넣기 요청과 상태 초기화만 검증했습니다."
            )
            response.placed_book_title = held_title
            response.result_json = self.mission_result_json
            self.state["held_book_title"] = ""
            self.state["held_from_shelf_id"] = -1
            self.state["last_place_result_json"] = self.mission_result_json
            self.save_state()
            return response

        command = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            "book_storage_place_sequence",
            "--ros-args",
            *self.mission_common_args(),
            "-p",
            f"marker2_alignment_target_marker_id:={storage_id}",
            "-p",
            f"marker2_alignment_dry_run:={'true' if self.dry_run else 'false'}",
            "-p",
            f"marker2_alignment_auto_run:={'true' if self.auto_run else 'false'}",
            "-p",
            "marker2_alignment_enabled:=true",
            "-p",
            "regrip_after_marker2_alignment:=true",
            "-p",
            "marker2_place_after_regrip_enabled:=true",
        ]

        self.busy = True
        try:
            returncode = self.run_command(command, self.place_timeout_sec)
            result = self.read_mission_status() or {}
            status = str(result.get("status", ""))
            success = returncode == 0 and status == "storage_marker_aligned_regripped_marker2_placed"
            response.success = bool(success)
            response.result_json = self.mission_result_json
            if success:
                response.placed_book_title = held_title
                response.message = "보관함에 책을 넣었습니다."
                self.state["held_book_title"] = ""
                self.state["held_from_shelf_id"] = -1
                self.state["last_place_result_json"] = self.mission_result_json
                self.save_state()
            else:
                response.placed_book_title = ""
                response.message = (
                    f"보관함 넣기 실패: returncode={returncode}, status={status}, "
                    f"abort_reason={result.get('abort_reason')}"
                )
            return response
        except subprocess.TimeoutExpired:
            response.success = False
            response.message = "보관함 넣기 미션이 시간 초과되었습니다."
            response.placed_book_title = ""
            response.result_json = self.mission_result_json
            return response
        finally:
            self.busy = False


def main(args=None):
    rclpy.init(args=args)
    node = BookMissionServiceServer()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
