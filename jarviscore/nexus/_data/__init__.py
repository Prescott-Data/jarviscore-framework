"""
jarviscore.nexus._data
======================
Static data bundled into the pip wheel:
  - docker-compose.nexus.yml  (local dev stack)
  - 001_initial_schema.sql    (broker DB schema)

This package also exports PROVIDER_URLS so the nexus CLI can seed the
broker DB with the correct auth/token endpoints without needing the
broker binary's catalog.
"""

PROVIDER_URLS: dict = {
    "linkedin": {
        "auth_url":          "https://www.linkedin.com/oauth/v2/authorization",
        "token_url":         "https://www.linkedin.com/oauth/v2/accessToken",
        "user_info_endpoint":"https://api.linkedin.com/v2/userinfo",
    },
    "github": {
        "auth_url":          "https://github.com/login/oauth/authorize",
        "token_url":         "https://github.com/login/oauth/access_token",
        "user_info_endpoint":"https://api.github.com/user",
    },
    "slack": {
        "auth_url":          "https://slack.com/oauth/v2/authorize",
        "token_url":         "https://slack.com/api/oauth.v2.access",
        "user_info_endpoint":"https://slack.com/api/users.identity",
    },
    "gmail": {
        "auth_url":          "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url":         "https://oauth2.googleapis.com/token",
        "user_info_endpoint":"https://www.googleapis.com/oauth2/v3/userinfo",
        "issuer":            "https://accounts.google.com",
    },
    "google_sheets": {
        "auth_url":          "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url":         "https://oauth2.googleapis.com/token",
        "user_info_endpoint":"https://www.googleapis.com/oauth2/v3/userinfo",
    },
    "google_drive": {
        "auth_url":          "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url":         "https://oauth2.googleapis.com/token",
        "user_info_endpoint":"https://www.googleapis.com/oauth2/v3/userinfo",
    },
    "google_calendar": {
        "auth_url":          "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url":         "https://oauth2.googleapis.com/token",
        "user_info_endpoint":"https://www.googleapis.com/oauth2/v3/userinfo",
    },
    "hubspot": {
        "auth_url":          "https://app.hubspot.com/oauth/authorize",
        "token_url":         "https://api.hubapi.com/oauth/v1/token",
        "user_info_endpoint":"https://api.hubapi.com/oauth/v1/access-tokens/",
    },
    "notion": {
        "auth_url":          "https://api.notion.com/v1/oauth/authorize",
        "token_url":         "https://api.notion.com/v1/oauth/token",
        "user_info_endpoint":"https://api.notion.com/v1/users/me",
    },
    "salesforce": {
        "auth_url":          "https://login.salesforce.com/services/oauth2/authorize",
        "token_url":         "https://login.salesforce.com/services/oauth2/token",
        "user_info_endpoint":"https://login.salesforce.com/services/oauth2/userinfo",
    },
    "x": {
        "auth_url":          "https://twitter.com/i/oauth2/authorize",
        "token_url":         "https://api.twitter.com/2/oauth2/token",
        "user_info_endpoint":"https://api.twitter.com/2/users/me",
    },
    "bitbucket": {
        "auth_url":          "https://bitbucket.org/site/oauth2/authorize",
        "token_url":         "https://bitbucket.org/site/oauth2/access_token",
        "user_info_endpoint":"https://api.bitbucket.org/2.0/user",
    },
    "linear": {
        "auth_url":          "https://linear.app/oauth/authorize",
        "token_url":         "https://api.linear.app/oauth/token",
        "user_info_endpoint":"https://api.linear.app/graphql",
    },
    "quickbooks": {
        "auth_url":          "https://appcenter.intuit.com/connect/oauth2",
        "token_url":         "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "user_info_endpoint":"https://accounts.platform.intuit.com/v1/openid_connect/userinfo",
    },
}
