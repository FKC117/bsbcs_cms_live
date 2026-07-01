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
