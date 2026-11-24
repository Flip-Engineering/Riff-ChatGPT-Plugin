"""The Skills extension (io.modelcontextprotocol/skills, specification/beta/skills.mdx of
modelcontextprotocol/ext-skills) on the Riff MCP server.

The catalog is checked against the specification's own example skill, whose files, sizes and
digests the specification publishes, and the server serves the plugin's own riff-studio skill.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "server"))
from main import RPC
import skills

CURRENT = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": CURRENT, "io.modelcontextprotocol/clientCapabilities": {}}

# The "Example Message Flow" of skills.mdx: pdf-processing with two templates.
SPEC_FILES = {
    "SKILL.md": "---\nname: pdf-processing\ndescription: Extract, fill, and assemble PDF documents\n---\n\n"
                "# PDF processing\n\nChoose the matching template from `templates/`.\n",
    "templates/invoice.md": "# Invoice\n\nCustomer:\nAmount:\n",
    "templates/purchase-order.md": "# Purchase order\n\nSupplier:\nItems:\n",
}
SPEC_ENTRY = {
    "uri": "skill://pdf-processing/SKILL.md",
    "frontmatter": {"name": "pdf-processing", "description": "Extract, fill, and assemble PDF documents"},
    "resources": [
        {"uri": "skill://pdf-processing/SKILL.md",
         "digest": "sha256:99b737495721155ece826d57521e2d66141ebdc1344a400487481ea2642ab19e", "size": 151},
        {"uri": "skill://pdf-processing/templates/invoice.md",
         "digest": "sha256:61f4ea6d2c75fde1b4977219e7e3107d491c3c26aefb6686e84d6281c088d9ee", "size": 29},
        {"uri": "skill://pdf-processing/templates/purchase-order.md",
         "digest": "sha256:f2ff774b1737ff3dec81c47946f9976f18a1a9f69dda0a81f22eabd95173c158", "size": 35},
    ],
}


def request(method, params=None, *, modern=True):
    params = dict(params or {})
    if modern:
        params["_meta"] = META
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


class Unused:
    """The adapter is never reached by a skills request."""

    def __getattr__(self, name):
        raise AssertionError(f"a skills request reached the adapter: {name}")


class SkillsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        for name, text in SPEC_FILES.items():
            path = root / "pdf-processing" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.rpc = RPC(Unused(), skills.Catalog([root], log=lambda line: None))

    def tearDown(self):
        self.directory.cleanup()

    def result(self, response):
        self.assertNotIn("error", response, response)
        return response["result"]

    def test_the_entry_of_the_specification_example_is_the_entry_the_specification_shows(self):
        listed = self.result(self.rpc.handle(request("skills/list")))
        self.assertEqual(listed["skills"], [SPEC_ENTRY])
        self.assertEqual(listed["resultType"], "complete")
        self.assertIsInstance(listed["ttlMs"], int)
        self.assertIn(listed["cacheScope"], ("public", "private"))
        got = self.result(self.rpc.handle(request("skills/get", {"uri": SPEC_ENTRY["uri"]})))
        self.assertEqual(got["skill"], SPEC_ENTRY)

    def test_discovery_declares_the_extension_and_names_the_skills(self):
        discover = self.result(self.rpc.handle(request("server/discover")))
        self.assertEqual(discover["capabilities"]["extensions"][skills.EXTENSION], {"directoryRead": True})
        self.assertIn(SPEC_ENTRY["uri"], discover["instructions"])

    def test_files_are_read_and_directories_walked_by_uri(self):
        read = self.result(self.rpc.handle(request("resources/read", {"uri": SPEC_ENTRY["uri"]})))
        self.assertEqual(read["contents"], [{"uri": SPEC_ENTRY["uri"], "mimeType": "text/markdown",
                                             "text": SPEC_FILES["SKILL.md"]}])
        root = self.result(self.rpc.handle(request("resources/directory/read", {"uri": "skill://pdf-processing"})))
        self.assertEqual([(row["uri"], row["mimeType"]) for row in root["resources"]],
                         [("skill://pdf-processing/SKILL.md", "text/markdown"),
                          ("skill://pdf-processing/templates", "inode/directory")])

    def test_unknown_skills_and_non_directories_are_invalid_params(self):
        for method, uri in (("skills/get", "skill://acme/billing/chargebacks/SKILL.md"),
                            ("resources/directory/read", SPEC_ENTRY["uri"])):
            with self.subTest(method=method):
                self.assertEqual(self.rpc.handle(request(method, {"uri": uri}))["error"]["code"], -32602)

    def test_frontmatter_that_yaml_reads_as_another_type_is_refused(self):
        for value in ("true", "12", "null", "[a, b]", "a: b", "|"):
            with self.subTest(value=value), self.assertRaises(skills.SkillError):
                skills.frontmatter(f"---\nname: {value}\n---\n")


class ShippedSkillTest(unittest.TestCase):
    def test_the_server_serves_riff_studio_and_each_digest_is_the_digest_of_the_file_it_serves(self):
        rpc = RPC(Unused())
        listed = rpc.handle(request("skills/list"))["result"]["skills"]
        self.assertEqual([entry["uri"] for entry in listed], ["skill://riff-studio/SKILL.md"])
        for entry in listed:
            for file in entry["resources"]:
                content = rpc.handle(request("resources/read", {"uri": file["uri"]}))["result"]["contents"][0]
                data = content["text"].encode("utf-8")
                self.assertEqual(len(data), file["size"])
                self.assertEqual("sha256:" + hashlib.sha256(data).hexdigest(), file["digest"])


if __name__ == "__main__":
    unittest.main()
