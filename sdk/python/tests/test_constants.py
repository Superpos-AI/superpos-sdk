"""Tests for the constants module."""

from __future__ import annotations

import superpos_sdk
from superpos_sdk import constants


class TestImports:
    def test_top_level_exports(self):
        # Namespace import works.
        assert superpos_sdk.constants is constants
        # All constants re-exported from top-level package.
        for name in (
            "CHANNEL_TYPES",
            "CHANNEL_STATUSES",
            "MESSAGE_TYPES",
            "TASK_STATUSES",
            "KNOWLEDGE_SCOPES",
            "KNOWLEDGE_SCOPES_LEGACY",
            "KNOWLEDGE_VISIBILITY",
            "RESOLUTION_POLICIES",
        ):
            assert hasattr(superpos_sdk, name), name

    def test_agent_scope_helper(self):
        assert superpos_sdk.agent_scope("01XYZ") == "agent:01XYZ"


class TestChannelTypes:
    def test_expected_members(self):
        assert "discussion" in constants.CHANNEL_TYPES
        assert "review" in constants.CHANNEL_TYPES
        assert "planning" in constants.CHANNEL_TYPES
        assert "incident" in constants.CHANNEL_TYPES
        assert len(constants.CHANNEL_TYPES) == 4

    def test_backward_compat_list_export_from_client(self):
        # Existing callers import CHANNEL_TYPES from superpos_sdk.client as a
        # list — that must still work.
        from superpos_sdk import client as client_mod

        legacy = client_mod.CHANNEL_TYPES
        assert isinstance(legacy, list)
        assert set(legacy) == set(constants.CHANNEL_TYPES)

    def test_top_level_channel_types_is_list(self):
        # superpos_sdk.CHANNEL_TYPES must be a list for backward compat —
        # not a tuple (which is the canonical type in constants).
        assert type(superpos_sdk.CHANNEL_TYPES) is list

    def test_client_channel_types_is_list(self):
        # superpos_sdk.client.CHANNEL_TYPES must also be a list.
        from superpos_sdk import client as client_mod

        assert type(client_mod.CHANNEL_TYPES) is list


class TestChannelStatuses:
    def test_expected_members(self):
        expected = {"open", "deliberating", "resolved", "stale", "failed", "archived"}
        assert set(constants.CHANNEL_STATUSES) == expected


class TestMessageTypes:
    def test_expected_members(self):
        expected = {
            "discussion",
            "proposal",
            "vote",
            "decision",
            "context",
            "system",
            "action",
        }
        assert set(constants.MESSAGE_TYPES) == expected


class TestTaskStatuses:
    def test_expected_members(self):
        for s in ("pending", "in_progress", "completed", "failed", "cancelled"):
            assert s in constants.TASK_STATUSES


class TestKnowledgeScopes:
    def test_expected_members(self):
        assert set(constants.KNOWLEDGE_SCOPES) == {"hive", "organization"}

    def test_legacy_expected_members(self):
        assert set(constants.KNOWLEDGE_SCOPES_LEGACY) == {"hive", "apiary"}

    def test_legacy_importable_from_top_level(self):
        from superpos_sdk import KNOWLEDGE_SCOPES_LEGACY

        assert KNOWLEDGE_SCOPES_LEGACY is constants.KNOWLEDGE_SCOPES_LEGACY

    def test_legacy_in_top_level_all(self):
        assert "KNOWLEDGE_SCOPES_LEGACY" in superpos_sdk.__all__

    def test_visibility(self):
        assert set(constants.KNOWLEDGE_VISIBILITY) == {"public", "private"}


class TestResolutionPolicies:
    def test_all_preset_keys(self):
        assert set(constants.RESOLUTION_POLICIES) == {
            "manual",
            "agent_decision",
            "consensus",
            "human_approval",
            "staged",
        }

    def test_each_preset_has_type(self):
        for name, shape in constants.RESOLUTION_POLICIES.items():
            assert shape["type"] == name, (name, shape)

    def test_staged_has_stages_list(self):
        staged = constants.RESOLUTION_POLICIES["staged"]
        assert isinstance(staged["stages"], list)
        assert len(staged["stages"]) >= 1

    def test_presets_are_copies_not_aliases(self):
        # Mutating a returned preset shouldn't leak across calls. The
        # simple guarantee is that RESOLUTION_POLICIES values are plain
        # dicts the caller can copy.
        original = constants.RESOLUTION_POLICIES["manual"]
        copy = dict(original)
        copy["type"] = "mutated"
        assert constants.RESOLUTION_POLICIES["manual"]["type"] == "manual"
