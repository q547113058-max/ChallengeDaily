from routes.health import bp as health_bp
from routes.activities import bp as activities_bp
from routes.stats import bp as stats_bp
from routes.reports import bp as reports_bp
from routes.settings_routes import bp as settings_bp
from routes.webhooks import bp as webhooks_bp
from routes.auto_report import bp as auto_report_bp
from routes.backup import bp as backup_bp
from routes.notifications import bp as notifications_bp
from routes.exports import bp as exports_bp
from routes.agent import bp as agent_bp
from routes.app_rules import bp as app_rules_bp
from routes.profile import bp as profile_bp
from routes.deep_insight import bp as deep_insight_bp
from routes.pomodoro import bp as pomodoro_bp
from routes.todos import bp as todos_bp
from routes.diaries import bp as diaries_bp
from routes.achievements import bp as achievements_bp
from routes.countdowns import bp as countdowns_bp
from routes.chat import bp as chat_bp
from routes.habits import bp as habits_bp
from routes.week_plan import bp as week_plan_bp
from routes.auth_routes import auth_bp
from routes.privacy_routes import privacy_bp
from routes.report_channels import bp as report_channels_bp
from routes.study_room import bp as study_room_bp
from routes.rules_engine import bp as rules_engine_bp
from routes.goals import bp as goals_bp
from routes.data_import import bp as data_import_bp
from routes.coach import bp as coach_bp
from routes.insight import bp as insight_bp
from routes.imports import bp as imports_bp
from routes.preferences import bp as preferences_bp
from routes.audit import bp as audit_bp
from routes.calendar_routes import bp as calendar_bp
from routes.git_routes import bp as git_integration_bp
from routes.analytics_routes import bp as analytics_bp
from routes.ai_intel_routes import bp as ai_intel_bp
from routes.platform_routes import bp as platform_bp
from routes.delight_routes import bp as delight_bp
from routes.advanced_data_routes import bp as advanced_data_bp
from routes.smart_routes import bp as smart_bp
from routes.uiux_routes import bp as uiux_bp
from routes.integration_routes import bp as integration_bp
from routes.viz_routes import bp as viz_bp
from routes.smart_search_routes import bp as smart_search_bp
from routes.realtime_routes import bp as realtime_bp
from routes.accessibility_routes import bp as accessibility_bp
from routes.ml_basic_routes import bp as ml_basic_bp
from routes.nlp_routes import bp as nlp_bp
from routes.cv_routes import bp as cv_bp
from routes.privacy_dq_routes import bp as privacy_dq_bp
from routes.db_advanced_routes import bp as db_advanced_bp
from routes.cache_advanced_routes import bp as cache_advanced_bp
from routes.daily_card import bp as daily_card_bp
from routes.ritual import bp as ritual_bp
from routes.scheduler import bp as scheduler_bp
from routes.mubu_routes import bp as mubu_bp
from routes.mubu_routes import memory_bp

ALL_BLUEPRINTS = [
    health_bp,
    activities_bp,
    stats_bp,
    reports_bp,
    settings_bp,
    webhooks_bp,
    auto_report_bp,
    backup_bp,
    notifications_bp,
    exports_bp,
    agent_bp,
    app_rules_bp,
    profile_bp,
    deep_insight_bp,
    pomodoro_bp,
    todos_bp,
    diaries_bp,
    achievements_bp,
    countdowns_bp,
    chat_bp,
    habits_bp,
    week_plan_bp,
    auth_bp,
    privacy_bp,
    report_channels_bp,
    study_room_bp,
    rules_engine_bp,
    goals_bp,
    data_import_bp,
    coach_bp,
    insight_bp,
    imports_bp,
    preferences_bp,
    audit_bp,
    calendar_bp,
    git_integration_bp,
    analytics_bp,
    ai_intel_bp,
    platform_bp,
    delight_bp,
    advanced_data_bp,
    smart_bp,
    uiux_bp,
    integration_bp,
    viz_bp,
    smart_search_bp,
    realtime_bp,
    accessibility_bp,
    ml_basic_bp,
    nlp_bp,
    cv_bp,
    privacy_dq_bp,
    db_advanced_bp,
    cache_advanced_bp,
    daily_card_bp,
    ritual_bp,
    scheduler_bp,
    mubu_bp,
    memory_bp,
]
