return {
	"catppuccin/nvim",
	name = "catppuccin",
	priority = 1000,
	config = function()
		require("catppuccin").setup({
			background = { -- :h background
				light = "mocha",
				dark = "macchiato",
			},
		})
	end
}
