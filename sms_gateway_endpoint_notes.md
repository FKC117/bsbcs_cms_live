# SMS Gateway Endpoint Notes

This note summarizes the endpoints listed in `sms gateway/smpp.revesms.com.txt`, what each one is for, and which ones our project currently uses.

## Endpoints We Use

### 1. Single SMS endpoint
Purpose: send system-generated SMS such as registration submission, approval, confirmation, abstract updates, and membership updates.

Configured with:
- `SMS_GATEWAY_SINGLE_URL`

Recommended value:
- `https://smpp.revesms.com:7790/sendtext`

Used by code:
- `registration.sms.send_sms()`

### 2. Bulk SMS endpoint
Purpose: send bulk SMS from the dashboard bulk SMS portal.

Configured with:
- `SMS_GATEWAY_BULK_URL`

Recommended value:
- `http://smpp.revesms.com:7788/send`

Used by code:
- `registration.sms.send_bulk_sms()`

### 3. DLR / status endpoint
Purpose: check message delivery status later using provider message ID.

Configured with:
- `SMS_GATEWAY_DLR_URL`

Recommended value:
- `https://smpp.revesms.com:7790/getstatus`

Current status:
- configured in `.env`
- not yet used by our code

## Fallback Endpoint

### 4. Generic gateway URL
Purpose: fallback only.

Configured with:
- `SMS_GATEWAY_URL`

Recommended value:
- same as single SMS endpoint
- `https://smpp.revesms.com:7790/sendtext`

Current status:
- not the main route anymore
- kept as fallback for backward compatibility

## Other Endpoints In Provider Doc

### 5. HTTP single SMS endpoint
- `http://smpp.revesms.com:7788/sendtext`

Purpose:
- non-HTTPS version of single SMS

Current status:
- not preferred
- we use HTTPS single endpoint instead

### 6. HTTP single status endpoint
- `http://smpp.revesms.com:7788/getstatus`

Purpose:
- non-HTTPS version of single message status check

Current status:
- not used

### 7. Multi-status endpoint
- `http://smpp.revesms.com:7788/getmultistatus`

Purpose:
- fetch status for multiple provider message IDs at once

Current status:
- not used
- may be useful later if we build delivery reconciliation for bulk campaigns

### 8. Balance API
Examples:
- `https://smpp.revesms.com/sms/smsConfiguration/smsClientBalance.jsp?client=CLIENT_ID`
- `http://smpp.revesms.com/sms/smsConfiguration/smsClientBalance.jsp?client=CLIENT_ID`

Purpose:
- fetch account balance from the provider

Current status:
- not used

### 9. C panel / alternate API host
Examples:
- `http://apismpp.revesms.com/sendtext`
- `http://apismpp.revesms.com/getstatus`

Purpose:
- alternate provider host for similar actions

Current status:
- not used

### 10. White level / whitelabel / raw IP endpoints
Examples:
- `http://bulksms.smsvaults.work:7788/sendtext`
- `http://cpanel.smsvaults.work/sendtext`
- `http://103.177.125.106:7788/sendtext`
- `http://103.177.125.108/sendtext`

Purpose:
- provider alternatives, whitelabel access, or direct IP fallback

Current status:
- not used
- only consider these if provider explicitly instructs us to switch

## Request Format Note

The provider document shows query-string examples like:
- `/sendtext?apikey=...&secretkey=...`

Our code currently sends JSON POST requests to the same endpoint names.

This is valid for our integration because local testing already returned provider success responses such as:
- `Status = 0`
- `Text = ACCEPTD`

So we do not need to rewrite the request style right now.

## Character Limit Note

Provider guidance says to use `160` characters per SMS segment.

Configured in `.env` with:
- `SMS_MASKING_CHAR_LIMIT=160`
- `SMS_NON_MASKING_CHAR_LIMIT=160`

The bulk SMS UI uses these settings to:
- show character count
- estimate segment count
- estimate billed SMS units

## Current Recommended .env Shape

```env
SMS_ENABLED=True
SMS_GATEWAY_URL=https://smpp.revesms.com:7790/sendtext
SMS_GATEWAY_SINGLE_URL=https://smpp.revesms.com:7790/sendtext
SMS_GATEWAY_BULK_URL=http://smpp.revesms.com:7788/send
SMS_GATEWAY_DLR_URL=https://smpp.revesms.com:7790/getstatus
SMS_GATEWAY_API_KEY=...
SMS_GATEWAY_SECRET_KEY=...
SMS_GATEWAY_CALLER_ID=1234
SMS_GATEWAY_MASKING_CALLER_ID=1234
SMS_GATEWAY_NON_MASKING_CALLER_ID=1234
SMS_GATEWAY_HASH=
SMS_REQUEST_TIMEOUT=15
SMS_MASKING_CHAR_LIMIT=160
SMS_NON_MASKING_CHAR_LIMIT=160
```

## Practical Rule For Our Project

- Automatic system SMS uses the single endpoint.
- Dashboard bulk SMS uses the bulk endpoint.
- DLR endpoint is saved for future delivery tracking.
- We prefer HTTPS where the provider clearly supports it.
- We do not force HTTPS for bulk until the provider gives an HTTPS bulk URL.


## Endpoint Usage Matrix

| Endpoint | Purpose | Used Now | Where In Code |
|---|---|---:|---|
| `https://smpp.revesms.com:7790/sendtext` | Single/system SMS send | Yes | `registration.sms.send_sms()` |
| `http://smpp.revesms.com:7788/send` | Bulk/campaign SMS send | Yes | `registration.sms.send_bulk_sms()` |
| `https://smpp.revesms.com:7790/getstatus` | Single message delivery/status lookup | Yes | `registration.sms.query_sms_status()` |
| `http://smpp.revesms.com:7788/getmultistatus` | Multi-message campaign status lookup | Yes | `registration.sms.query_sms_multi_status()` |
| `https://smpp.revesms.com/sms/smsConfiguration/smsClientBalance.jsp` | Provider balance lookup | Yes | `registration.sms.query_sms_balance()` |
| `http://smpp.revesms.com:7788/sendtext` | HTTP fallback for single SMS | No | Not used |
| `http://smpp.revesms.com:7788/getstatus` | HTTP fallback for single status lookup | No | Not used |
| `http://bulksms.smsvaults.work:7788/sendtext` | Whitelabel single SMS send | No | Not used |
| `http://bulksms.smsvaults.work:7788/getstatus` | Whitelabel single status lookup | No | Not used |
| `http://103.177.125.106:7788/sendtext` | Raw IP single SMS send | No | Not used |
| `http://103.177.125.106:7788/getstatus` | Raw IP single status lookup | No | Not used |
| `http://apismpp.revesms.com/sendtext` | Alternate/cPanel single SMS send | No | Not used |
| `http://apismpp.revesms.com/getstatus` | Alternate/cPanel single status lookup | No | Not used |
| `http://cpanel.smsvaults.work/sendtext` | Whitelabel cPanel SMS send | No | Not used |
| `http://cpanel.smsvaults.work/getstatus` | Whitelabel cPanel status lookup | No | Not used |
| `http://103.177.125.108/sendtext` | Alternate raw IP single SMS send | No | Not used |
| `http://103.177.125.108/getstatus` | Alternate raw IP single status lookup | No | Not used |
| `https://smpp.revesms.com` | Billing/account portal | No | Portal only |
| `http://smpp.revesms.com` | Billing/account portal | No | Portal only |
| `http://103.177.125.109/login` | White-label login portal | No | Portal only |
| `smpp.revesms.com:9988` | SMPP integration port | No | Not used, we integrated via HTTP API |

## Old / Alternate Server Docs Not Used

These appeared in older provider materials and Postman collections, but our implementation does not use them:

| Endpoint | Purpose | Used Now |
|---|---|---:|
| `http://149.20.188.26:8124/sendtext` | Old single SMS server | No |
| `https://149.20.188.26:8125/sendtext` | Old HTTPS single SMS server | No |
| `http://149.20.188.26:8124/getstatus` | Old status server | No |
| `http://149.20.188.8:4479/sendtext` | Alternate old SMS server | No |
| `http://149.20.188.8:4479/getstatus` | Alternate old status server | No |
| `http://199.188.150.40:8124/api/v2/balance` | Old balance API | No |

## Practical Summary

- System-triggered SMS uses the single `sendtext` endpoint.
- Dashboard campaigns use the provider bulk/campaign `send` endpoint.
- Delivery confirmation is checked through `getstatus` and `getmultistatus`.
- Provider balance is checked through the balance JSP endpoint.
- We are not using SMPP, raw IP endpoints, whitelabel endpoints, or older alternate hosts.
