# Makefile for Sphinx documentation

# You can set these variables from the command line
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile

clean:
	rm -rf $(BUILDDIR)
	rm -rf $(SOURCEDIR)/examples
	rm -rf $(SOURCEDIR)/reference/generated

# # It might be necessary to start a web server when viewing docs locally
# # in the future if we ever get interactive PyVista/trame plots to work
# # with nbsphinx: https://github.com/pyvista/pyvista/discussions/4809
# serve-html:
# 	python -m http.server 0 --directory "$(BUILDDIR)"/html

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
