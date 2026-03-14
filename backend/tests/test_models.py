import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import MagicToken, VoteHistory


def test_magic_token_model_exists():
    assert MagicToken.__tablename__ == "magic_tokens"


def test_vote_history_model_exists():
    assert VoteHistory.__tablename__ == "vote_history"
