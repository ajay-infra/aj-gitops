# Behaviour tests for the APISIX authorization policy.
#
#   opa test opa/tests opa/  --  see .github/workflows/ci.yml
#
# Why these exist: `opa check` proves the policy COMPILES. It says nothing about
# whether an unsigned token is rejected, or whether an empty issuer list
# default-allows. Both are one typo away, and both fail open.
#
# ⚠ THE KEY BELOW IS A TEST FIXTURE. A 2048-bit RSA key generated for this file
# and used nowhere else, ever. It exists because io.jwt.decode_verify takes
# `secret` for HMAC and `cert` for asymmetric keys — production is RS256 with a
# JWKS in `cert`, so an HMAC test would pass while proving nothing about the
# path that actually runs. Do not reuse it. Do not treat a finding on it as a
# leak.

package apisix.authz_test

import rego.v1
import data.apisix.authz

priv_jwk := `{"kty": "RSA", "kid": "test-key", "alg": "RS256", "use": "sig", "n": "0w_XcF5R8noXEjfVzFBSYlJ_9wzXntUMvkGxs7yFn95Prf4KHPaU055WSCbAcVq_mdkQ68CImD8xd3p4Z4h5G_NBvEfIfKIIMFKkSz2F4QHUw_I-3qPCsr_BT_0jeSZaXpQXf9NCjPeoEKYdj4DiGmhh1mnHmO9stQt9bM2kDakGYiEkvBc7-CIgfWRSysNy14OieYxhFfXgvtjNaXmvTO5zOGYh_RVqVqxuCD8YnhUcsxAlDgm8l3ga4qHIYqX4TFxgScoHAj8vJgHi2mPEtEwoI_ereydepmyt5lQYyiMvKuMwoL_SkBRslXwxCKUTAtvkNJT-qajK1cw_YTAPFQ", "e": "AQAB", "d": "m2RvbpjS5p5C_DPFof6FGUS6WC7JVXRwRGdjqPwkuXZY3bZKxdY57rAFwGtfhlWU-XVaQuhm6Qilp9ywZzGQUSbBABktn61AMCu4MHkkZ2wMtRNWfF6_SxFpBzZNdrXpFPcdcgwdVGJGB7P10aDHV0AAwHby8ENemtDR0Fh6715qAj8ITlY2CVjnUufvlTYmsQhC1PKZjQRowWgttQMuAlLEtmUYRMM977GRK8dShIE8B71rgpCnk0vTOf1tkcNKiVA4eJvq2IavCftZx7Ta9uu92QNO0MdFvJIZrrrS7doM1setq8n2tBrmPvNnlX2vfU6Ibk41_Hs8wG0dMW85gQ", "p": "_RtzwyWY96jbvXgPNejyogdukH1J_3G52AtUbGSAbu8acfHd4qeMPGpwPjc7oiZZOS8hptdoFT6m66LlLgMQp4T_m7heefUpRh_UOPF8JQfzQr6hmOJZvT1QTSzMnDQ2XK7a_JyZ-aEHyjukR9ilHx2bfQySL0VeLDbYMsdgA6E", "q": "1XlfOLz40DhskUwUxPOnjJ_ZdRZfAfp-NN2uVGV7oCVJo-w8xvTUAtIN_eI7nDkj0SyP5J3d4ybc5YNLbTChKU1Noy-pnmB3JemwyukF__35rYo27Kf6DS212JF63y0DMTTCYnFkUW8Yt-ydIJ7wMfnsCkhl8C6Tlg3eDIjE1vU", "dp": "3UHEPpF9WPIptUVgtpW-lNm-U1zS9RSriyrMUDzC8TbffUAb4Wjp9F5vZFPQM30mfhCvcDPZbsjoDhDGGyTeyDJBaBURsbcYr45fbK_dAFok0vHmPcmQ_Ra-PditvNb_tqG8GRuklk2oi6b7gzrljX_KTtRQbjZLjocbE7iqPEE", "dq": "NuU4RGnr_feUi6Sp7p_NpU7x57cyBVs6GzQqgU97hAoyrrGwS2VoI7WKnZAQzjKvcDnqYtrp1WEICwlBWznXJ7zWSzGVh8G8wgYfTX6w6UyRaTwStbbYiY0Ip0F5_Gwh1wR_PDt2la5hB-MT4PCeSeu_9ED73dDMaRj10flVzQU", "qi": "HyhjKBnzIzrCiukXSKYNTGcIC_DgeAT-kzIHV6PmATredtansJ6M4Xi3o_OIdiszdeIgv3bzO_yKniKaJdUpBNUMJcLImpAghyXD-Oz42aOYBDFmXWNC8G1pGnqTD7vYRoNoUbd49aWRDPouLtA4wqXNdPIspz1uV3ovUtGZhMI"}`

jwks := `{"keys": [{"kty": "RSA", "kid": "test-key", "alg": "RS256", "use": "sig", "n": "0w_XcF5R8noXEjfVzFBSYlJ_9wzXntUMvkGxs7yFn95Prf4KHPaU055WSCbAcVq_mdkQ68CImD8xd3p4Z4h5G_NBvEfIfKIIMFKkSz2F4QHUw_I-3qPCsr_BT_0jeSZaXpQXf9NCjPeoEKYdj4DiGmhh1mnHmO9stQt9bM2kDakGYiEkvBc7-CIgfWRSysNy14OieYxhFfXgvtjNaXmvTO5zOGYh_RVqVqxuCD8YnhUcsxAlDgm8l3ga4qHIYqX4TFxgScoHAj8vJgHi2mPEtEwoI_ereydepmyt5lQYyiMvKuMwoL_SkBRslXwxCKUTAtvkNJT-qajK1cw_YTAPFQ", "e": "AQAB"}]}`

issuers_fixture := {"providers": [{
	"iss": "https://kc.example.com/realms/platform",
	"aud": "aj-platform",
	"jwks": jwks,
}]}

token(payload) := io.jwt.encode_sign(
	{"typ": "JWT", "alg": "RS256", "kid": "test-key"},
	payload,
	json.unmarshal(priv_jwk),
)

req(path, hdrs) := {"request": {"method": "GET", "path": path, "headers": hdrs}}

bearer(t) := {"authorization": concat("", ["Bearer ", t])}

good_claims := {
	"iss": "https://kc.example.com/realms/platform",
	"aud": "aj-platform",
	"tenant": "acme",
	"realm_access": {"roles": ["viewer"]},
}

test_public_path_needs_no_token if {
	authz.allow with input as req("/healthz", {}) with data.issuers as issuers_fixture
}

test_missing_token_is_denied_401 if {
	p := req("/api/v1/laps", {})
	not authz.allow with input as p with data.issuers as issuers_fixture
	authz.status_code == 401 with input as p with data.issuers as issuers_fixture
}

test_valid_token_is_allowed if {
	p := req("/api/v1/laps", bearer(token(good_claims)))
	authz.allow with input as p with data.issuers as issuers_fixture
}

test_wrong_issuer_is_denied if {
	p := req("/api/v1/laps", bearer(token(object.union(good_claims, {"iss": "https://evil.example.com/"}))))
	not authz.allow with input as p with data.issuers as issuers_fixture
}

test_wrong_audience_is_denied if {
	p := req("/api/v1/laps", bearer(token(object.union(good_claims, {"aud": "some-other-api"}))))
	not authz.allow with input as p with data.issuers as issuers_fixture
}

test_valid_token_without_tenant_is_denied_403 if {
	p := req("/api/v1/laps", bearer(token(object.remove(good_claims, {"tenant"}))))
	not authz.allow with input as p with data.issuers as issuers_fixture
	authz.status_code == 403 with input as p with data.issuers as issuers_fixture
}

test_valid_token_without_roles_is_denied if {
	p := req("/api/v1/laps", bearer(token(object.remove(good_claims, {"realm_access"}))))
	not authz.allow with input as p with data.issuers as issuers_fixture
}

# The failure mode that matters most: an empty trust store must deny, never
# default-allow. This is what the shipped placeholder ConfigMap evaluates to.
test_empty_issuer_list_denies_everything if {
	p := req("/api/v1/laps", bearer(token(good_claims)))
	not authz.allow with input as p with data.issuers as {"providers": []}
}

test_garbage_token_is_denied if {
	p := req("/api/v1/laps", bearer("not.a.jwt"))
	not authz.allow with input as p with data.issuers as issuers_fixture
}
