"""Agent capability gatekeeper and tool permission enforcement."""

from pathlib import Path
from typing import Set, Dict, Any, Optional
from backend.app.models.agent import AgentRole


class SecurityViolationError(PermissionError):
    """Raised when an agent attempts an action or tool forbidden for its role."""
    pass


class AgentPermissionGatekeeper:
    """
    Central permission enforcement layer.
    Guarantees least-privilege tool access for all specialized agents.
    """

    # Static capability whitelist per role
    ROLE_PERMISSIONS: Dict[AgentRole, Set[str]] = {
        AgentRole.PLANNER: {
            "read_file",
            "list_directory",
            "search_codebase",
            "inspect_dependencies",
            "submit_plan",
        },
        AgentRole.CODER: {
            "read_file",
            "write_staging_file",
            "edit_staging_file",
            "delete_staging_file",
            "generate_diff",
            "submit_proposal",
        },
        AgentRole.TEST_ARCHITECT: {
            "read_file",
            "list_directory",
            "inspect_proposal_diff",
            "inspect_approved_plan",
            "submit_test_plan",
        },
        AgentRole.TEST_EXECUTOR: {
            "read_file",
            "run_sandbox_command",
            "read_sandbox_output",
            "record_baseline_result",
            "record_test_result",
            "emit_failure_report",
        },
        AgentRole.REVIEWER: {
            "read_file",
            "inspect_project_structure",
            "inspect_approved_plan",
            "inspect_proposed_diff",
            "inspect_test_plan",
            "inspect_test_results",
            "inspect_build_logs",
            "inspect_execution_history",
            "inspect_agent_outputs",
            "submit_review_report",
        },
    }

    CAPABILITIES = {
        "FILE_READ", "FILE_SEARCH", "STAGING_FILE_WRITE", "STAGING_FILE_DELETE",
        "APPROVED_FILE_WRITE", "COMMAND_EXECUTE", "SANDBOX_EXECUTE",
        "TEST_PLAN_CREATE", "TEST_CASE_CREATE", "DIFF_PROPOSE",
        "APPROVAL_CREATE", "LOADOUT_CHANGE", "FINAL_REVIEW",
    }

    @classmethod
    def assert_tool_permitted(cls, role: AgentRole, tool_name: str) -> None:
        """Verify that the tool is authorized for the given agent role."""
        allowed_tools = cls.ROLE_PERMISSIONS.get(role, set())
        if tool_name not in allowed_tools:
            raise SecurityViolationError(
                f"Security Violation: Agent role '{role.value}' is prohibited from invoking tool '{tool_name}'."
            )

    @classmethod
    def assert_staging_path_only(cls, file_path: str, staging_root: str) -> None:
        """
        Verify that a write/edit/delete operation target is strictly within the staging directory.
        Approved workspace paths are read-only.
        """
        root = Path(staging_root).resolve()
        target = Path(file_path).resolve()
        if target != root and root not in target.parents:
            raise SecurityViolationError(
                f"Security Violation: File modification target '{file_path}' is outside the authorized staging directory '{staging_root}'."
            )

    @classmethod
    def assert_action_allowed(
        cls,
        role: AgentRole,
        capability: str,
        target_resource: Optional[str] = None,
        staging_root: Optional[str] = None,
        workflow_state: Optional[str] = None,
    ) -> None:
        """Enforce role, storage boundary, and workflow context together."""
        if capability not in cls.CAPABILITIES:
            raise SecurityViolationError(f"Unknown capability '{capability}'.")
        mapping = {
            "FILE_READ": "read_file",
            "FILE_SEARCH": "search_codebase",
            "STAGING_FILE_WRITE": "write_staging_file",
            "STAGING_FILE_DELETE": "delete_staging_file",
            "COMMAND_EXECUTE": "run_sandbox_command",
            "SANDBOX_EXECUTE": "run_sandbox_command",
            "TEST_PLAN_CREATE": "submit_test_plan",
            "TEST_CASE_CREATE": "submit_test_plan",
            "DIFF_PROPOSE": "generate_diff",
            "FINAL_REVIEW": "submit_review_report",
        }
        if capability in mapping:
            cls.assert_tool_permitted(role, mapping[capability])
        elif capability == "APPROVED_FILE_WRITE" and role != AgentRole.CODER:
            raise SecurityViolationError("Approved workspace writes are not permitted.")
        elif capability in {"APPROVAL_CREATE", "LOADOUT_CHANGE"}:
            raise SecurityViolationError(f"Agent role '{role.value}' cannot perform {capability}.")
        if capability in {"STAGING_FILE_WRITE", "STAGING_FILE_DELETE"}:
            if not staging_root or not target_resource:
                raise SecurityViolationError("A staging root and target resource are required.")
            cls.assert_staging_path_only(target_resource, staging_root)
        if capability == "APPROVED_FILE_WRITE":
            raise SecurityViolationError("Approved workspace writes are denied in Phase 5.")
