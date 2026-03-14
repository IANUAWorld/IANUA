import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import (
    DraftShareToken, DraftComment, AmendmentSupport,
    TierChallenge, ContentReport, AdminAction, AuditResponse
)


def test_all_new_models_exist():
    assert DraftShareToken.__tablename__ == "draft_share_tokens"
    assert DraftComment.__tablename__ == "draft_comments"
    assert AmendmentSupport.__tablename__ == "amendment_supports"
    assert TierChallenge.__tablename__ == "tier_challenges"
    assert ContentReport.__tablename__ == "content_reports"
    assert AdminAction.__tablename__ == "admin_actions"
    assert AuditResponse.__tablename__ == "audit_responses"
