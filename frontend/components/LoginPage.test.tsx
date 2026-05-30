import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LoginPage from "./LoginPage";
import { AuthProvider } from "../context/AuthContext";

// ─── Module mocks (must be hoisted) ────────────────────────────────

const mocks = vi.hoisted(() => ({
	navigate: vi.fn(),
	apiRequest: vi.fn(),
	apiGet: vi.fn(),
}));

vi.mock("react-router-dom", async (importOriginal) => {
	const actual = await importOriginal<typeof import("react-router-dom")>();
	return {
		...actual,
		useNavigate: () => mocks.navigate,
	};
});

vi.mock("../services/api", () => ({
	api: {
		request: mocks.apiRequest,
		get: mocks.apiGet,
	},
}));

// ─── Render helper ─────────────────────────────────────────────────

const renderLoginPage = () => {
	return render(
		<MemoryRouter>
			<AuthProvider>
				<LoginPage />
			</AuthProvider>
		</MemoryRouter>,
	);
};

describe("LoginPage", () => {
	beforeEach(() => {
		localStorage.clear();
		mocks.navigate.mockClear();
		mocks.apiRequest.mockReset();
		mocks.apiGet.mockReset();
		mocks.apiGet.mockRejectedValue(new Error("Not authenticated"));
	});

	// ─── 1. Form Rendering ───────────────────────────────────────────

	describe("form rendering", () => {
		it("renders the login form with username and password inputs", () => {
			renderLoginPage();

			// NOTE: Labels in LoginPage are not associated with inputs via htmlFor,
			// so we query by placeholder text instead.
			expect(screen.getByPlaceholderText("admin")).toBeInTheDocument();
			expect(screen.getByPlaceholderText(/•••/)).toBeInTheDocument();
		});

		it("renders the submit button with AUTHENTICATE text", () => {
			renderLoginPage();

			expect(
				screen.getByRole("button", { name: /authenticate/i }),
			).toBeInTheDocument();
		});

		it("renders the NEX-GEN branding", () => {
			renderLoginPage();

			expect(screen.getByText("NEX-GEN")).toBeInTheDocument();
			expect(screen.getByText(/secure access gateway/i)).toBeInTheDocument();
		});

		it("inputs are initially empty", () => {
			renderLoginPage();

			const usernameInput = screen.getByPlaceholderText(
				"admin",
			) as HTMLInputElement;
			const passwordInput = screen.getByPlaceholderText(
				/•••/,
			) as HTMLInputElement;

			expect(usernameInput.value).toBe("");
			expect(passwordInput.value).toBe("");
		});

		it("password input has type password", () => {
			renderLoginPage();

			const passwordInput = screen.getByPlaceholderText(/•••/);
			expect(passwordInput).toHaveAttribute("type", "password");
		});
	});

	// ─── 2. Input Changes ────────────────────────────────────────────

	describe("input changes", () => {
		it("updates username when typing", async () => {
			const user = userEvent.setup();
			renderLoginPage();

			const usernameInput = screen.getByPlaceholderText("admin");
			await user.type(usernameInput, "admin");

			expect(usernameInput).toHaveValue("admin");
		});

		it("updates password when typing", async () => {
			const user = userEvent.setup();
			renderLoginPage();

			const passwordInput = screen.getByPlaceholderText(/•••/);
			await user.type(passwordInput, "secret123");

			expect(passwordInput).toHaveValue("secret123");
		});
	});

	// ─── 3. Submission Behavior ──────────────────────────────────────

	describe("submission behavior", () => {
		it("calls api.request with correct endpoint and form data on submit", async () => {
			const user = userEvent.setup();
			mocks.apiRequest.mockResolvedValue({ access_token: "test-token" });
			mocks.apiGet.mockResolvedValue({
				username: "admin",
				role: "ADMIN",
				permissions: [],
				allowed_locations: [],
			});

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "secret");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(mocks.apiRequest).toHaveBeenCalledWith("/auth/token", {
					method: "POST",
					headers: { "Content-Type": "application/x-www-form-urlencoded" },
					body: expect.any(URLSearchParams),
				});
			});

			// Verify the body contains the right credentials
			const callArgs = mocks.apiRequest.mock.calls[0][1];
			const body = callArgs.body as URLSearchParams;
			expect(body.get("username")).toBe("admin");
			expect(body.get("password")).toBe("secret");
		});

		it("fetches user details after successful token exchange", async () => {
			const user = userEvent.setup();
			const mockUser = {
				username: "admin",
				role: "ADMIN",
				permissions: [],
				allowed_locations: [],
			};
			mocks.apiRequest.mockResolvedValue({ access_token: "test-token" });
			mocks.apiGet.mockResolvedValue(mockUser);

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "secret");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(mocks.apiGet).toHaveBeenCalledWith("/auth/users/me");
			});
		});
	});

	// ─── 4. Success Handling ─────────────────────────────────────────

	describe("success handling", () => {
		it("does not store token in localStorage on successful cookie-auth login", async () => {
			const user = userEvent.setup();
			const mockUser = {
				username: "admin",
				role: "ADMIN",
				permissions: [],
				allowed_locations: [],
			};
			mocks.apiRequest.mockResolvedValue({ access_token: "success-token" });
			mocks.apiGet.mockResolvedValue(mockUser);

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "pass");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(mocks.navigate).toHaveBeenCalledWith("/");
			});
			expect(localStorage.getItem("token")).toBeNull();
		});

		it('navigates to home page ("/") on successful login', async () => {
			const user = userEvent.setup();
			const mockUser = {
				username: "admin",
				role: "ADMIN",
				permissions: [],
				allowed_locations: [],
			};
			mocks.apiRequest.mockResolvedValue({ access_token: "tok" });
			mocks.apiGet.mockResolvedValue(mockUser);

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "pass");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(mocks.navigate).toHaveBeenCalledWith("/");
			});
		});

		it("clears any previous error message on new submission", async () => {
			const user = userEvent.setup();
			// First submission fails to show an error
			mocks.apiRequest.mockRejectedValueOnce(new Error("Invalid credentials"));

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "wrong");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
			});

			// Second submission succeeds — error should disappear
			mocks.apiRequest.mockResolvedValue({ access_token: "tok" });
			mocks.apiGet.mockResolvedValue({
				username: "admin",
				role: "ADMIN",
				permissions: [],
				allowed_locations: [],
			});

			await user.type(screen.getByPlaceholderText(/•••/), "correct");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(
					screen.queryByText("Invalid credentials"),
				).not.toBeInTheDocument();
			});
		});
	});

	// ─── 5. Error Handling ───────────────────────────────────────────

	describe("error handling", () => {
		it("displays error message when api.request fails", async () => {
			const user = userEvent.setup();
			mocks.apiRequest.mockRejectedValue(new Error("Invalid credentials"));

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "wrong");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
			});
		});

		it('displays generic "Login failed" message when error has no message', async () => {
			const user = userEvent.setup();
			mocks.apiRequest.mockRejectedValue({});

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "wrong");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(screen.getByText("Login failed")).toBeInTheDocument();
			});
		});

		it("does not write localStorage token on login failure", async () => {
			const user = userEvent.setup();
			mocks.apiRequest.mockRejectedValue(new Error("Auth error"));

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "wrong");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(screen.getByText("Auth error")).toBeInTheDocument();
			});
			expect(localStorage.getItem("token")).toBeNull();
		});

		it("does NOT navigate on failure", async () => {
			const user = userEvent.setup();
			mocks.apiRequest.mockRejectedValue(new Error("Bad creds"));

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "wrong");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(screen.getByText("Bad creds")).toBeInTheDocument();
			});

			expect(mocks.navigate).not.toHaveBeenCalled();
		});

		it("does NOT call /auth/users/me for login when token request fails", async () => {
			const user = userEvent.setup();
			mocks.apiRequest.mockRejectedValue(new Error("Network error"));

			renderLoginPage();
			mocks.apiGet.mockClear();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "pass");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(screen.getByText("Network error")).toBeInTheDocument();
			});

			expect(mocks.apiGet).not.toHaveBeenCalled();
		});
	});

	// ─── 6. Navigation Interactions ──────────────────────────────────

	describe("navigation interactions", () => {
		it("does not navigate on initial render", () => {
			renderLoginPage();

			expect(mocks.navigate).not.toHaveBeenCalled();
		});

		it("navigates only after both api calls succeed", async () => {
			const user = userEvent.setup();

			// Token succeeds but user fetch fails
			mocks.apiRequest.mockResolvedValue({ access_token: "tok" });
			mocks.apiGet.mockRejectedValue(new Error("User fetch failed"));

			renderLoginPage();

			await user.type(screen.getByPlaceholderText("admin"), "admin");
			await user.type(screen.getByPlaceholderText(/•••/), "pass");
			await user.click(screen.getByRole("button", { name: /authenticate/i }));

			await waitFor(() => {
				expect(screen.getByText("User fetch failed")).toBeInTheDocument();
			});

			// Should NOT have navigated because the user fetch failed
			expect(mocks.navigate).not.toHaveBeenCalled();
		});
	});
});
