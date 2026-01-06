-- Enable line numbers
vim.wo.number = true

-- Disable line wrapping
-- TODO

-- Disable NetRW
vim.g.loaded_netrw = 1
vim.g.loaded_netrwPlugin = 1

-- Initialise lazy.nvim plugin manager
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.loop.fs_stat(lazypath) then
	vim.fn.system({
		"git",
		"clone",
		"--filter=blob:none",
		"https://github.com/folke/lazy.nvim.git",
		"--branch=stable", -- latest stable release
		lazypath,
	})
end
vim.opt.rtp:prepend(lazypath)

-- Set `mapleader` before lazy.nvim setup so mappings are correct
vim.g.mapleader = " "

-- lazy.nvim options
local lazy_opts = {
  git = {
    -- defaults for the `Lazy log` command
    -- log = { "-10" }, -- show the last 10 commits
    log = { '--since=3 days ago' }, -- show commits from the last 3 days
    timeout = 90,                   -- seconds
    url_format = 'https://github.com/%s.git',
  },
  dev = {
    -- directory where you store your local plugin projects
    path = '~/code/nvim',
    ---@type string[] plugins that match these patterns will use your local versions instead of being fetched from GitHub
    patterns = {}, -- For example {"folke"}
  },
  install = {
    -- install missing plugins on startup. This doesn't increase startup time.
    missing = true,
    -- try to load one of these colorschemes when starting an installation during startup
    -- colorscheme = { 'habamax' },
  },
  ui = {
    size = { width = 0.8, height = 0.8 },
    border = 'none',
    icons = {
      loaded = '●',
      not_loaded = '○',
      cmd = ' ',
      config = '',
      event = '',
      ft = ' ',
      init = ' ',
      keys = ' ',
      plugin = ' ',
      runtime = ' ',
      source = ' ',
      start = '',
      task = '✔ ',
      lazy = '鈴 ',
      list = {
        '●',
        '➜',
        '★',
        '‒',
      },
    },
    custom_keys = {
      -- you can define custom key maps here.
      -- To disable one of the defaults, set it to false

      -- open lazygit log
      ['<localleader>l'] = function(plugin)
        require('lazy.util').open_cmd({ 'lazygit', 'log' }, {
          cwd = plugin.dir,
          terminal = true,
          close_on_exit = true,
          enter = true,
        })
      end,

      -- open a terminal for the plugin dir
      ['<localleader>t'] = function(plugin)
        require('lazy.util').open_cmd({ vim.go.shell }, {
          cwd = plugin.dir,
          terminal = true,
          close_on_exit = true,
          enter = true,
        })
      end,
    },
  },
  diff = { cmd = 'diffview.nvim' },
  checker = {
    -- automatically check for plugin updates
    enabled = false,
    concurrency = nil, ---@type number? set to 1 to check for updates very slowly
    notify = true,    -- get a notification when new updates are found
    frequency = 3600, -- check for updates every hour
  },
  change_detection = {
    enabled = true,
    notify = true, -- get a notification when changes are found
  },
  performance = {
    cache = {
      enabled = true,
      path = vim.fn.stdpath('cache') .. '/lazy/cache',
      disable_events = { 'VimEnter', 'BufReadPre' },
      ttl = 3600 * 24 * 5, -- keep unused modules for up to 5 days
    },
    reset_packpath = true, -- reset the package path to improve startup time
    rtp = {
      reset = true,        -- reset the runtime path to $VIMRUNTIME and your config directory
      ---@type string[]
      paths = {},          -- add any custom paths here that you want to incluce in the rtp
      ---@type string[] list any plugins you want to disable here
      disabled_plugins = {},
    },
  },
  readme = {
    root = vim.fn.stdpath('state') .. '/lazy/readme',
    files = { 'README.md' },
    -- only generate markdown helptags for plugins that dont have docs
    skip_if_doc_exists = true,
  },
}

-- Load lazy.nvim plugins
require('lazy').setup('steveplays.plugins', lazy_opts)

-- Load and set color scheme
require("catppuccin").setup({
  flavour = "mocha",   -- latte, frappe, macchiato, mocha
  background = {       -- :h background
    light = "latte",
    dark = "mocha",
  },
  transparent_background = true,   -- disables setting the background color.
  term_colors = false,              -- sets terminal colors (e.g. `g:terminal_color_0`)
  dim_inactive = {
    enabled = false,                -- dims the background color of inactive window
    shade = "dark",
    percentage = 0.15,              -- percentage of the shade to apply to the inactive window
  },
  no_italic = false,                -- Force no italic
  no_bold = false,                  -- Force no bold
  no_underline = false,             -- Force no underline
})

vim.cmd.colorscheme "catppuccin"

-- Load Neoconf
require("neoconf").setup()

-- Load Neoscroll
require('neoscroll').setup()

-- Load Telescope
require("telescope").load_extension "file_browser"

-- Load Neotree
require('neo-tree').setup()

-- Load Wilder (command completion)
local wilder = require('wilder')
wilder.setup({ modes = { ':', '/', '?' } })

wilder.set_option('pipeline', {
  wilder.branch(
    wilder.cmdline_pipeline({
      -- Sets the language to use, 'vim' and 'python' are supported
      language = 'vim',
      -- 0 turns off fuzzy matching
      -- 1 turns on fuzzy matching
      -- 2 partial fuzzy matching (match does not have to begin with the same first letter)
      fuzzy = 1,
    })
  ),
})

wilder.set_option('renderer', wilder.popupmenu_renderer({
  highlighter = wilder.basic_highlighter(),
  left = { ' ', wilder.popupmenu_devicons() },
  right = { ' ', wilder.popupmenu_scrollbar() },
}))

-- Setup language servers
local lspconfig = require('lspconfig')
lspconfig.pyright.setup( {})
lspconfig.tsserver.setup( {})
lspconfig.rust_analyzer.setup( {
  -- Server-specific settings. See `:help lspconfig-setup`
  settings = {
    ['rust-analyzer'] = {},
  },
})
lspconfig.jdtls.setup( {})

-- Global mappings
-- See `:help vim.diagnostic.*` for documentation on any of the below functions
vim.keymap.set('n', '<space>e', vim.diagnostic.open_float)
vim.keymap.set('n', '[d', vim.diagnostic.goto_prev)
vim.keymap.set('n', ']d', vim.diagnostic.goto_next)
vim.keymap.set('n', '<space>q', vim.diagnostic.setloclist)

-- Use LspAttach autocommand to only map the following keys
-- after the language server attaches to the current buffer
vim.api.nvim_create_autocmd('LspAttach', {
  group = vim.api.nvim_create_augroup('UserLspConfig', {}),
  callback = function(ev)
    -- Enable completion triggered by <c-x><c-o>
    vim.bo[ev.buf].omnifunc = 'v:lua.vim.lsp.omnifunc'

    -- Buffer local mappings.
    -- See `:help vim.lsp.*` for documentation on any of the below functions
    local opts = { buffer = ev.buf }
    vim.keymap.set('n', 'gD', vim.lsp.buf.declaration, opts)
    vim.keymap.set('n', 'gd', vim.lsp.buf.definition, opts)
    vim.keymap.set('n', 'K', vim.lsp.buf.hover, opts)
    vim.keymap.set('n', 'gi', vim.lsp.buf.implementation, opts)
    vim.keymap.set('n', '<C-k>', vim.lsp.buf.signature_help, opts)
    vim.keymap.set('n', '<space>wa', vim.lsp.buf.add_workspace_folder, opts)
    vim.keymap.set('n', '<space>wr', vim.lsp.buf.remove_workspace_folder, opts)
    vim.keymap.set('n', '<space>wl', function()
      print(vim.inspect(vim.lsp.buf.list_workspace_folders()))
    end, opts)
    vim.keymap.set('n', '<space>D', vim.lsp.buf.type_definition, opts)
    vim.keymap.set('n', '<space>rn', vim.lsp.buf.rename, opts)
    vim.keymap.set({ 'n', 'v' }, '<space>ca', vim.lsp.buf.code_action, opts)
    vim.keymap.set('n', 'gr', vim.lsp.buf.references, opts)
    vim.keymap.set('n', '<space>f', function()
      vim.lsp.buf.format { async = true }
    end, opts)
  end,
})
