# TASK-037: Credential Vault (Encrypt/Decrypt Service)

**Status:** in-progress
**Branch:** `task/037-credential-vault`
**PR:** —
**Depends on:** TASK-036
**Blocks:** TASK-042 (Service proxy controller)

## Objective

Create a `CredentialVault` service that provides apiary-aware encryption and
decryption of sensitive credentials. In CE mode it delegates to Laravel's
default encrypter (APP_KEY). In Cloud mode it uses per-apiary encryption keys
stored on the `apiaries` table, falling back to APP_KEY when no per-apiary key
exists.

## Requirements

### Functional

- [ ] FR-1: Add `encryption_key` column (nullable TEXT) to `apiaries` table
- [ ] FR-2: `encryption_key` is encrypted at rest via Laravel `encrypted` cast
- [ ] FR-3: `encryption_key` is hidden from JSON serialisation
- [ ] FR-4: `CredentialVault::encrypt(string, ?apiaryId)` encrypts a string value
- [ ] FR-5: `CredentialVault::decrypt(string, ?apiaryId)` decrypts a string value
- [ ] FR-6: `CredentialVault::encryptArray(array, ?apiaryId)` encrypts an array
- [ ] FR-7: `CredentialVault::decryptArray(string, ?apiaryId)` decrypts to array
- [ ] FR-8: `CredentialVault::generateKey()` produces a valid AES-256-CBC key
- [ ] FR-9: CE mode always uses default Laravel encrypter regardless of apiaryId
- [ ] FR-10: Cloud mode uses per-apiary key when present, falls back to default

### Non-Functional

- [ ] NFR-1: PSR-12 compliant
- [ ] NFR-2: Plaintext credentials never logged
- [ ] NFR-3: Service is stateless — safe for dependency injection

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/0001_01_01_000018_add_encryption_key_to_apiaries_table.php` | Add encryption_key column |
| Create | `app/Services/CredentialVault.php` | Encrypt/decrypt service |
| Modify | `app/Models/Superpos.php` | Add encryption_key to fillable, hidden, casts |
| Create | `tests/Feature/CredentialVaultTest.php` | Feature tests |

### Key Design Decisions

- Per-apiary key is base64-encoded AES-256-CBC key, stored encrypted via
  Laravel's `encrypted` cast (double-envelope: APP_KEY protects the per-apiary
  key at rest).
- `resolveEncrypter()` is private — callers use the high-level encrypt/decrypt
  API without knowing which key is in use.
- In CE mode the apiaryId parameter is ignored, keeping the single-tenant path
  zero-overhead.

## Database Changes

```sql
ALTER TABLE apiaries ADD COLUMN encryption_key TEXT;
```

## Test Plan

### Feature Tests

- [ ] encrypt → decrypt round-trip returns original string (CE mode)
- [ ] encryptArray → decryptArray round-trip returns original array (CE mode)
- [ ] decrypt with wrong ciphertext throws DecryptException
- [ ] decryptArray with non-array payload throws DecryptException
- [ ] generateKey produces valid base64-encoded 32-byte key
- [ ] Cloud mode without per-apiary key falls back to default encrypter
- [ ] Cloud mode with per-apiary key uses that key
- [ ] Cloud data encrypted with per-apiary key cannot be decrypted with default
- [ ] encryption_key is hidden from Superpos JSON serialisation
- [ ] encryption_key is encrypted at rest (stored value differs from plaintext)

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] No plaintext credentials in logs
- [ ] Service is injectable via Laravel container
