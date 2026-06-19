#!/usr/bin/env python3
"""Run only the storage-side sequence: align marker, re-grip, place book."""

import rclpy

from .book_mission_state_machine import BookMissionStateMachine


class BookStoragePlaceSequence(BookMissionStateMachine):
    def execute(self):
        self.trace_state("START", "ok", mode="book_storage_place_sequence")

        self.marker2_alignment_enabled = True
        self.regrip_after_marker2_alignment = True
        self.marker2_place_after_regrip_enabled = True

        if not self.pause_between_states("ALIGN_MARKER2_AFTER_TEMP_PLACE"):
            return self.abort("user_cancelled")
        self.state = "ALIGN_MARKER2_AFTER_TEMP_PLACE"
        self.trace_state(self.state, "running")
        if not self.run_marker2_alignment_stage():
            return self.abort(
                "marker2_alignment_stage_failed",
                marker2_alignment_result=self.result.get("marker2_alignment_result"),
            )
        self.trace_state(
            self.state,
            "ok",
            marker2_alignment_result=self.result.get("marker2_alignment_result"),
        )

        if not self.pause_between_states("REGRIP_TEMP_BOOK"):
            return self.abort("user_cancelled")
        self.state = "REGRIP_TEMP_BOOK"
        self.trace_state(self.state, "running")
        if not self.run_regrip_temp_book_stage():
            return self.abort(
                "regrip_temp_book_failed",
                regrip_temp_book_result=self.result.get("regrip_temp_book_result"),
            )
        self.trace_state(
            self.state,
            "ok",
            regrip_temp_book_result=self.result.get("regrip_temp_book_result"),
        )

        if not self.pause_between_states("PLACE_BOOK_AT_MARKER2"):
            return self.abort("user_cancelled")
        self.state = "PLACE_BOOK_AT_MARKER2"
        self.trace_state(self.state, "running")
        if not self.run_marker2_place_book_stage():
            return self.abort(
                "marker2_place_book_failed",
                marker2_place_result=self.result.get("marker2_place_result"),
            )
        self.trace_state(
            self.state,
            "ok",
            marker2_place_result=self.result.get("marker2_place_result"),
        )

        self.state = "DONE"
        self.result["status"] = "storage_marker_aligned_regripped_marker2_placed"
        self.trace_state(self.state, "ok")
        self.save_final_result()
        return True


def main(args=None):
    rclpy.init(args=args)
    node = BookStoragePlaceSequence()
    try:
        ok = node.execute()
        if ok:
            node.get_logger().info("Storage place sequence completed successfully.")
        else:
            node.get_logger().error(
                f"Storage place sequence finished in state {node.state} "
                f"with status {node.result.get('status')}"
            )
    finally:
        node.shutdown()
        node.destroy_node()


if __name__ == "__main__":
    main()
