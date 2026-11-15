# Official social publishing feasibility

Researched 15 November 2026 from the official documentation linked below. No accounts were connected and no uploads were attempted. TikTok pages show explicit update dates; Meta pages generally do not. Approval durations are not estimated.

## Decision-relevant conclusions

- **TikTok is the principal constraint for a personal, fully unattended clipper.** Direct public publishing exists, but its permitted product design and audit requirements matter as much as its endpoints. Draft upload is a different feature and does not finish publishing.
- **Instagram Reels and Facebook Page Reels have supported upload-and-publish APIs.** Instagram requires a professional account; Facebook Reels publishing targets Pages. Own-account access and onboarding arbitrary customers have different review requirements, detailed below.
- **A completed upload is not a published post.** Implement asynchronous processing checks and confirm the published result, including visibility outside the developer’s account. Meta explicitly says Development-mode test posts are visible only to app-role users. [Meta app modes](https://developers.facebook.com/documentation/development/build-and-test/app-modes)

## TikTok

### Direct publishing versus draft upload

`POST /v2/post/publish/video/init/` uses `video.publish`, queries creator information first, and initializes a direct post after the user supplies metadata and explicitly consents. It supports `FILE_UPLOAD` and `PULL_FROM_URL`, returns a tracking `publish_id`, and is limited to six initialization requests/minute per user token. Unaudited-client posts remain private. The reference was updated **27 October 2026**. [Direct Post API reference](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post)

An app needs TikTok approval for `video.publish` **and** authorization from the target TikTok user. Completing integration tests does not itself remove the visibility restriction: the client needs an audit. [Direct Post getting started](https://developers.tiktok.com/docs/en/content-posting-api-get-started)

`POST /v2/post/publish/inbox/video/init/` uses `video.upload` and uploads **without posting**. Users must open the inbox notification in TikTok and complete the editing/posting flow. It supports file transfer or a verified URL/domain, six initialization requests/minute/token, and at most five pending shares within a 24-hour period. [Upload API reference](https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video) The draft flow also requires app approval for its scope and target-user authorization. [Upload getting started](https://developers.tiktok.com/docs/en/content-posting-api-get-started-upload-content)

### Audit, product restrictions, and creator control

The guidelines, updated **4 August 2026**, require original creator content and a product for a broad audience. They explicitly disallow arbitrary cross-platform copying and a utility limited to accounts the developer/team manages. Unaudited clients allow at most five posting users/24h, all private accounts, with `SELF_ONLY` posts. Direct Post additionally has a client creator cap set from audit estimates, plus a creator posting cap shared across clients, typically about 15/day and variable.

The required UI retrieves current creator information, shows the account, previews content, permits title editing, requires manual privacy selection without a default, and provides comment/duet/stitch controls respecting creator settings. It includes commercial-content disclosure and the required music/branded-content consents. Upload begins only after express consent; users retain awareness/control. Server-hosted media should use `PULL_FROM_URL` from an ownership-verified domain/prefix. [Content Sharing Guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines)

**Inference:** Treat “automatically post every selected highlight to my own/team’s TikTok accounts” as an unsupported Direct Post product premise unless TikTok explicitly accepts the actual use case. An audited creator-facing product with compliant review/consent controls is materially different. Draft export plus human completion is a credible fallback, subject to the draft scope approval.

### OAuth maintenance

The token-management page, updated **5 November 2026**, currently specifies **two-hour access tokens and 180-day refresh tokens**; it instructs developers to use returned expiry fields rather than hard-coded lifetimes. Refresh rotates the refresh token, so atomically persist the replacement. [Manage OAuth access tokens](https://developers.tiktok.com/docs/en/oauth-user-access-token-management)

## Instagram

### Account eligibility and login choices

The API supports professional **Business and Creator** accounts. Consumer/personal accounts are unsupported; the Facebook Login setup allows Reels publishing for both professional types. [Instagram API with Facebook Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/)

Current official docs describe **three** setups. **Unified Login** is recommended for new integrations: the user signs in with Instagram or Facebook; no Facebook Page is required, but a business portfolio is required. It returns a Business Integration System User access token and calls `graph.facebook.com`. Existing **Instagram Login** uses an Instagram user token and `graph.instagram.com`, without a Page or login-flow business portfolio requirement. Existing **Facebook Login** needs a linked Facebook Page and uses Facebook user/Page tokens. [Compare Instagram setups](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/)

Unified Login publishing uses `instagram_basic` and `instagram_content_publish`. Its permissions have Standard Access for app-role testing; non-role clients require Advanced Access through App Review and an appropriate live/production configuration. [Unified Login permissions](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/permissions) Instagram Login equivalents are `instagram_business_basic` and `instagram_business_content_publish`; Facebook Login also needs `pages_read_engagement`, with additional ad permissions possible for roles assigned through Business Manager. [Container permissions reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container)

### Upload, process, publish

Create `/{ig-id}/media` with `media_type=REELS` and `video_url`; Meta fetches the media from a publicly accessible server. Then publish the resulting container with `/{ig-id}/media_publish` and its `creation_id`. Resumable upload through `rupload.facebook.com/ig-api-upload/...` is also documented, **only for apps implementing Facebook Login for Business**, including the compatible Unified Login setup. Therefore, “Instagram always requires a permanent public video URL” is too broad. A required Page Publishing Authorization on a linked Page can block publishing. [Content publishing guide](https://developers.facebook.com/documentation/instagram-platform/content-publishing)

Poll the container’s `status_code`: `FINISHED` means ready; `PUBLISHED` means published; `ERROR` requires handling; unpublished containers expire after 24 hours. [Container status reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container)

**Quota discrepancy in the official docs:** the main guide says **100 API-published posts per rolling 24h**, but its carousel subsection says **50**. The dedicated quota reference also documents `config.quota_total=50` over `86400` seconds. Query `/{ig-id}/content_publishing_limit` and use returned `config` and `quota_usage`; do not contractually promise 100/day from these inconsistent pages. A carousel counts as one post. [Publishing guide rate limit](https://developers.facebook.com/documentation/instagram-platform/content-publishing), [Quota reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit)

### Own-account MVP versus customer product

Instagram’s review table explicitly says an app only for a business the developer owns/manages can use Standard Access without App Review; an app serving multiple businesses requires Advanced Access and review. Review requires an externally testable product, login demonstration, use-case explanation, and permission-specific screencasts. [Instagram App Review](https://developers.facebook.com/documentation/instagram-platform/app-review) Advanced Access also requires Business Verification. A UI-less private app cannot obtain publishing approval through the limited private-app review exception. [Instagram overview](https://developers.facebook.com/documentation/instagram-platform/overview)

Unified Login can be tested with an invited Instagram professional tester in Development mode; Meta test users are unsupported. [Unified Login setup](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/get-started) Its business integration token expiration depends on the selected configuration; it can be invalidated when the client removes the app or moves the Instagram account to another portfolio. [Unified Login authentication](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/authentication)

## Facebook Reels

The Reels API publishes **only to Facebook Pages**, including crossposting; it does not support a personal profile. A Page post has implicit public audience, and the app should disclose sharing and offer the appropriate public selection. Obtain a Page token from a user with `CREATE_CONTENT`, granting `pages_show_list`, `pages_read_engagement`, and `pages_manage_posts` through Facebook Login.

Flow: initialize `/{page-id}/video_reels` with `upload_phase=start`; upload local bytes or a public hosted file to the returned `rupload.facebook.com` URL; check `/{video-id}?fields=status`; finish with `upload_phase=finish` and `video_state=PUBLISHED`. Upload success alone is insufficient. The limit is **30 API-published Reels/rolling 24h/Page**. Current documented media bounds include 9:16 and 3–90 seconds. [Facebook Reels publishing guide](https://developers.facebook.com/documentation/video-api/guides/reels-publishing)

Facebook Login for Business is preferred for accessing client business assets; `/me/accounts` supplies Page IDs and Page tokens. App-role users can develop/test; business apps require Advanced Access before non-role users can grant permissions. [Pages API overview](https://developers.facebook.com/documentation/pages-api/overview) Advanced Access requires Business Verification; request only the permissions used. [Meta permissions requirements](https://developers.facebook.com/documentation/development/permissions)

A short-lived Facebook user token can be exchanged for a roughly 60-day user token; using a long-lived user token to retrieve a Page token produces a long-lived Page token with **no scheduled expiration**, but it can still be invalidated. This is not a guarantee of permanent connectivity. [Facebook long-lived tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens/get-long-lived)

## Remaining verification before implementation

1. Resolve account types and ownership: professional Instagram accounts, Facebook Pages, and which TikTok product/access scope is actually approved.
2. Check App Dashboard use case, access levels, mode, business verification and supported permissions. Meta documentation mixes business apps without modes and mode-based app language; verify the chosen app’s production configuration explicitly.
3. Publish a controlled authorized test and verify it from outside the app-role/developer session. A success response, developer-visible post or draft is not evidence of public availability.
4. Use returned quotas, processing states, token expiry and revocation signals; avoid treating per-minute initiation limits as permission to publish that often.

Several Meta endpoints intermittently returned HTTP 429 during research; the cited pages were nevertheless retrieved successfully. The dedicated `media_publish` reference and token invalidation details page could not be fetched, so no additional claims from those pages are assumed.
