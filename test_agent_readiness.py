import unittest
import os
import json
import hashlib

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

class TestAgentReadiness(unittest.TestCase):
    def test_robots_txt_content_signals_and_agentmap(self):
        path = os.path.join(REPO_ROOT, "robots.txt")
        self.assertTrue(os.path.isfile(path), "robots.txt must exist")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Content-Signal:", content)
        self.assertIn("Agentmap:", content)

    def test_index_html_agent_links(self):
        path = os.path.join(REPO_ROOT, "index.html")
        self.assertTrue(os.path.isfile(path), "index.html must exist")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('rel="api-catalog"', content)
        self.assertIn('rel="ai-catalog"', content)
        self.assertIn('rel="describedby"', content)

    def test_auth_md(self):
        path = os.path.join(REPO_ROOT, "auth.md")
        self.assertTrue(os.path.isfile(path), "auth.md must exist")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(content.startswith("# auth.md"))
        self.assertIn("oauth-authorization-server", content)
        self.assertIn("openid-configuration", content)
        self.assertIn("oauth-protected-resource", content)

    def test_openapi_mpp(self):
        path = os.path.join(REPO_ROOT, "openapi.json")
        self.assertTrue(os.path.isfile(path), "openapi.json must exist")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        self.assertIn("x-service-info", doc)
        self.assertIn("/api/premium-report", doc["paths"])
        op = doc["paths"]["/api/premium-report"]["get"]
        self.assertIn("x-payment-info", op)
        self.assertEqual(op["x-payment-info"]["method"], "stripe")

    def test_api_catalog(self):
        path = os.path.join(REPO_ROOT, ".well-known", "api-catalog")
        self.assertTrue(os.path.isfile(path), "api-catalog must exist")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        self.assertIn("linkset", doc)
        self.assertTrue(len(doc["linkset"]) > 0)
        self.assertIn("service-desc", doc["linkset"][0])

    def test_openid_configuration(self):
        path = os.path.join(REPO_ROOT, ".well-known", "openid-configuration")
        self.assertTrue(os.path.isfile(path), "openid-configuration must exist")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        for key in ["issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"]:
            self.assertIn(key, doc)

    def test_oauth_authorization_server(self):
        path = os.path.join(REPO_ROOT, ".well-known", "oauth-authorization-server")
        self.assertTrue(os.path.isfile(path), "oauth-authorization-server must exist")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        for key in ["issuer", "authorization_endpoint", "token_endpoint", "agent_auth"]:
            self.assertIn(key, doc)

    def test_oauth_protected_resource(self):
        path = os.path.join(REPO_ROOT, ".well-known", "oauth-protected-resource")
        self.assertTrue(os.path.isfile(path), "oauth-protected-resource must exist")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        for key in ["resource", "authorization_servers", "scopes_supported", "bearer_methods_supported"]:
            self.assertIn(key, doc)

    def test_jwks_and_web_bot_auth(self):
        for fname in ["jwks.json", "http-message-signatures-directory"]:
            path = os.path.join(REPO_ROOT, ".well-known", fname)
            self.assertTrue(os.path.isfile(path), f"{fname} must exist")
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            self.assertIn("keys", doc)
            self.assertTrue(len(doc["keys"]) > 0)
            key = doc["keys"][0]
            self.assertEqual(key.get("kty"), "RSA")

    def test_a2a_agent_card_and_ap2(self):
        path = os.path.join(REPO_ROOT, ".well-known", "agent-card.json")
        self.assertTrue(os.path.isfile(path), "agent-card.json must exist")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        self.assertIn("supportedInterfaces", doc)
        self.assertIn("capabilities", doc)
        self.assertIn("skills", doc)
        self.assertIn("extensions", doc)
        ap2_ext = next((e for e in doc["extensions"] if "AP2" in e.get("uri", "")), None)
        self.assertIsNotNone(ap2_ext, "AP2 extension must be present in agent card")
        self.assertIn("merchant", ap2_ext.get("params", {}).get("roles", []))

    def test_agent_skills_index_and_digest(self):
        index_path = os.path.join(REPO_ROOT, ".well-known", "agent-skills", "index.json")
        skill_path = os.path.join(REPO_ROOT, ".well-known", "agent-skills", "bluey-pricing", "SKILL.md")
        self.assertTrue(os.path.isfile(index_path), "agent-skills index must exist")
        self.assertTrue(os.path.isfile(skill_path), "bluey-pricing SKILL.md must exist")
        with open(skill_path, "r", encoding="utf-8") as f:
            skill_content = f.read()
        calculated_digest = "sha256:" + hashlib.sha256(skill_content.encode("utf-8")).hexdigest()
        with open(index_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc.get("$schema"), "https://schemas.agentskills.io/discovery/0.2.0/schema.json")
        self.assertTrue(len(doc.get("skills", [])) > 0)
        self.assertEqual(doc["skills"][0]["digest"], calculated_digest)

    def test_mcp_server_card(self):
        path = os.path.join(REPO_ROOT, ".well-known", "mcp", "server-card.json")
        self.assertTrue(os.path.isfile(path), "server-card.json must exist")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        self.assertIn("serverInfo", doc)
        self.assertIn("capabilities", doc)

    def test_acp_and_ucp(self):
        acp_path = os.path.join(REPO_ROOT, ".well-known", "acp.json")
        ucp_path = os.path.join(REPO_ROOT, ".well-known", "ucp")
        self.assertTrue(os.path.isfile(acp_path), "acp.json must exist")
        self.assertTrue(os.path.isfile(ucp_path), "ucp must exist")
        with open(acp_path, "r", encoding="utf-8") as f:
            acp = json.load(f)
        self.assertEqual(acp.get("protocol", {}).get("name"), "acp")
        with open(ucp_path, "r", encoding="utf-8") as f:
            ucp = json.load(f)
        self.assertIn("protocol_version", ucp)

    def test_ai_catalog_ard_and_poppy(self):
        ard_path = os.path.join(REPO_ROOT, ".well-known", "ai-catalog.json")
        poppy_path = os.path.join(REPO_ROOT, ".well-known", "poppy.json")
        self.assertTrue(os.path.isfile(ard_path), "ai-catalog.json must exist")
        self.assertTrue(os.path.isfile(poppy_path), "poppy.json must exist")
        with open(ard_path, "r", encoding="utf-8") as f:
            ard = json.load(f)
        self.assertIn("entries", ard)
        with open(poppy_path, "r", encoding="utf-8") as f:
            poppy = json.load(f)
        self.assertEqual(poppy.get("protocol_version"), "0.1")

    def test_vercel_json_configuration(self):
        path = os.path.join(REPO_ROOT, "vercel.json")
        with open(path, "r", encoding="utf-8") as f:
            vjson = json.load(f)
        
        # Verify Link header on /
        root_headers = next((h for h in vjson.get("headers", []) if h.get("source") == "/"), None)
        self.assertIsNotNone(root_headers)
        link_h = next((kv for kv in root_headers["headers"] if kv.get("key") == "Link"), None)
        self.assertIsNotNone(link_h)
        self.assertIn("api-catalog", link_h["value"])

        # Verify markdown content negotiation rewrite
        md_rewrite = next((r for r in vjson.get("rewrites", []) if any("text/markdown" in h.get("value", "") for h in r.get("has", []))), None)
        self.assertIsNotNone(md_rewrite)

if __name__ == "__main__":
    unittest.main()
