import os
import pytest
from unittest.mock import patch
from investment_policy_manager import InvestmentPolicyManager, DEFAULT_POLICY_PROMPT

@pytest.fixture
def policy_manager(tmp_path):
    test_file = os.path.join(tmp_path, "test_investment_policy.json")
    return InvestmentPolicyManager(filepath=test_file)

def test_default_config(policy_manager):
    config = policy_manager.load_config()
    assert "api_key" not in config
    assert config["selected_model"] == "gemini-flash-latest"
    assert "インカムゲイン特化型" in config["policy_prompt"]

def test_save_config(policy_manager):
    with patch.dict(os.environ, {}, clear=True):
        policy_manager.save_config(
            api_key="test_api_key_12345",
            selected_model="gemini-flash-lite-latest",
            policy_prompt="カスタム投資方針テスト"
        )
        config = policy_manager.load_config()
        assert "api_key" not in config
        assert policy_manager.get_effective_api_key() == "test_api_key_12345"
        assert config["selected_model"] == "gemini-flash-lite-latest"
        assert config["policy_prompt"] == "カスタム投資方針テスト"

def test_masked_config(policy_manager):
    with patch.dict(os.environ, {}, clear=True):
        policy_manager.save_config(api_key="AIzaSy1234567890")
        masked_info = policy_manager.get_masked_config()
        assert masked_info["api_key_masked"] == "AIza...7890"
        assert masked_info["has_api_key"] is True
        assert masked_info["is_using_env_key"] is False

def test_reset_policy_prompt(policy_manager):
    policy_manager.save_config(policy_prompt="変更した方針")
    assert policy_manager.load_config()["policy_prompt"] == "変更した方針"
    
    policy_manager.reset_policy_prompt()
    assert "インカムゲイン特化型" in policy_manager.load_config()["policy_prompt"]

def test_get_effective_api_key_from_env(policy_manager):
    policy_manager.save_config(api_key="")
    with patch.dict(os.environ, {"GEMINI_API_KEY": "env_api_key_xyz"}, clear=True):
        assert policy_manager.get_effective_api_key() == "env_api_key_xyz"

def test_masked_config_short_key_and_env_key(policy_manager):
    with patch.dict(os.environ, {}, clear=True):
        # 短いキー（8文字以下）
        policy_manager.save_config(api_key="1234567")
        masked = policy_manager.get_masked_config()
        assert masked["api_key_masked"] == "********"
        assert masked["has_api_key"] is True
        assert masked["is_using_env_key"] is False

    # キーなしで環境変数あり
    policy_manager.save_config(api_key="")
    with patch.dict(os.environ, {"GEMINI_API_KEY": "env_key_abc"}, clear=True):
        masked_env = policy_manager.get_masked_config()
        assert masked_env["api_key_masked"] == "env_..._abc"
        assert masked_env["has_api_key"] is True
        assert masked_env["is_using_env_key"] is True

def test_load_config_with_missing_keys(policy_manager):
    # 一部キーのみのファイル作成
    with open(policy_manager.filepath, "w", encoding="utf-8") as f:
        import json
        json.dump({"selected_model": "gemini-flash-lite-latest"}, f)
    
    config = policy_manager.load_config()
    assert config["selected_model"] == "gemini-flash-lite-latest"
    assert "policy_prompt" in config
    assert "api_key" not in config

def test_load_config_corrupted_file(policy_manager):
    # 破損ファイル
    with open(policy_manager.filepath, "w", encoding="utf-8") as f:
        f.write("{ invalid json")
    
    config = policy_manager.load_config()
    assert "api_key" not in config
    assert config["selected_model"] == "gemini-flash-latest"

