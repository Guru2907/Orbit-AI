# API Rate Limits

Flowspace provides a REST API for teams who want to integrate Flowspace
with other tools.

Rate limits by plan:
- Free plan: 100 API requests per hour
- Pro plan: 1,000 API requests per hour
- Business plan: 5,000 API requests per hour

If you exceed your rate limit, the API returns a 429 status code
("Too Many Requests"). You should wait until the next hourly window
before retrying.

Each API response includes these headers so you can track your usage:
- X-RateLimit-Limit: your total allowed requests per hour
- X-RateLimit-Remaining: requests remaining in the current window
- X-RateLimit-Reset: when the limit resets (Unix timestamp)

API keys can be generated under Settings > Developer > API Keys. Business
plan customers can request a higher custom rate limit by contacting
support.
