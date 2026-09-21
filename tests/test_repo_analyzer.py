import unittest

from scripts.repo_analyzer import analyze_repository, select_code_evidence_paths


class RepositoryRankingSignalsTest(unittest.TestCase):
    def test_complete_full_stack_app_outranks_frontend_only_app(self):
        repo = {
            "name": "complete-app",
            "description": "Production application",
            "topics": [],
            "homepage": "https://example.com",
            "pushed_at": "2026-09-01T00:00:00Z",
            "stargazers_count": 0,
            "fork": False,
            "archived": False,
        }
        full_stack_tree = [
            {"type": "blob", "path": f"frontend/src/components/C{i}.tsx"} for i in range(20)
        ] + [
            {"type": "blob", "path": f"backend/routes/r{i}.ts"} for i in range(20)
        ] + [
            {"type": "blob", "path": "backend/models/User.ts"},
            {"type": "blob", "path": "package.json"},
            {"type": "blob", "path": ".github/workflows/ci.yml"},
            {"type": "blob", "path": "Dockerfile"},
        ]
        full_stack = analyze_repository(
            repo,
            full_stack_tree,
            "React Express MongoDB REST API JWT authentication",
            {"package.json": '"react" "express" "mongoose" "jsonwebtoken" "jest"'},
            {"TypeScript": 1000},
        )
        frontend = analyze_repository(
            {**repo, "name": "ui-only"},
            [{"type": "blob", "path": f"src/components/C{i}.tsx"} for i in range(40)],
            "React user interface",
            {"package.json": '"react" "vite"'},
            {"TypeScript": 1000},
        )

        self.assertTrue(full_stack["full_stack"])
        self.assertFalse(frontend["full_stack"])
        self.assertGreater(full_stack["score"], frontend["score"])

    def test_tutorial_repository_is_not_eligible(self):
        result = analyze_repository(
            {
                "name": "react-tutorial",
                "description": "Learning exercise",
                "topics": [],
                "homepage": "",
                "pushed_at": "2026-09-01T00:00:00Z",
                "stargazers_count": 0,
                "fork": False,
                "archived": False,
            },
            [{"type": "blob", "path": f"src/File{i}.tsx"} for i in range(10)],
            "React tutorial",
            {"package.json": '"react"'},
            {"TypeScript": 100},
        )
        self.assertFalse(result["eligible"])

    def test_code_evidence_prioritizes_implementation_files(self):
        tree = [
            {"type": "blob", "path": "frontend/src/styles.css", "size": 1000},
            {"type": "blob", "path": "backend/src/controllers/orderController.js", "size": 3000},
            {"type": "blob", "path": "backend/src/routes/orders.js", "size": 2000},
            {"type": "blob", "path": "frontend/src/pages/Checkout.jsx", "size": 2000},
            {"type": "blob", "path": "dist/app.bundle.js", "size": 2000},
        ]

        selected = select_code_evidence_paths(tree, limit=3)

        self.assertEqual(selected[0], "backend/src/controllers/orderController.js")
        self.assertIn("backend/src/routes/orders.js", selected)
        self.assertNotIn("dist/app.bundle.js", selected)


if __name__ == "__main__":
    unittest.main()
