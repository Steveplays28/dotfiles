return {
	"rachartier/tiny-inline-diagnostic.nvim",
	event = "VeryLazy",
	priority = 1000,
	config = function()
		require("tiny-inline-diagnostic").setup({
			signs = {
				left = "",
				right = "",
				diag = "",
				arrow = "",
				up_arrow = "",
				vertical = "  │",
				vertical_end = "  └",
            },
            hi = {
                error = "DiagnosticError",     -- Highlight for error diagnostics
                warn = "DiagnosticWarn",       -- Highlight for warning diagnostics
                info = "DiagnosticInfo",       -- Highlight for info diagnostics
                hint = "DiagnosticInfo",       -- Highlight for hint diagnostics
                arrow = "NonText",             -- Highlight for the arrow pointing to diagnostic
                background = "CursorLine",     -- Background highlight for diagnostics
                mixing_color = "Normal",       -- Color to blend background with (or "None")
            },
			options = {
				multilines = {
					enabled = true,
				},
				show_related = {
					enabled = false,
				},
			},
		})
		vim.diagnostic.config({ virtual_text = false }) -- Disable Neovim's default virtual text diagnostics
	end,
}
