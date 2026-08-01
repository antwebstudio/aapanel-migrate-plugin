#!/bin/bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

#Configure the plugin installation directory
install_path=/www/server/panel/plugin/antweb_ssh_migrate

# Script tag that must load on every panel page so the injected "Migrate" tab
# (static/js/site_tab.js) can attach itself to the website Settings modal
# whenever it opens. aaPanel does not expose an official hook for this, so we
# patch the panel's main template as a best-effort, reversible step: a backup
# is kept and restored on uninstall, and nothing is touched if none of the
# candidate files can be found.
inject_marker_start='<!-- ANTWEB_SSH_MIGRATE_PLUGIN_START (do not edit, managed by antweb_ssh_migrate plugin) -->'
inject_marker_end='<!-- ANTWEB_SSH_MIGRATE_PLUGIN_END -->'
inject_snippet='<script type="text/javascript" src="/antweb_ssh_migrate/static/js/site_tab.js"></script>'

# Locations for aaPanel's main template, loaded once per session as the SPA
# shell (the site Settings dialog itself is rendered client-side into
# <div id="app"> afterwards). index_new.html is the modern Vue/naive-ui build;
# index.html is kept as a fallback for older aaPanel installs still on the
# classic UI.
template_candidates=(
	/www/server/panel/BTPanel/templates/default/index_new.html
	/www/server/panel/BTPanel/templates/default/index.html
)

find_template() {
	for f in "${template_candidates[@]}"; do
		if [ -f "$f" ]; then
			echo "$f"
			return 0
		fi
	done
	return 1
}

patch_template() {
	local tpl="$1"

	if grep -qF "$inject_marker_start" "$tpl" 2>/dev/null; then
		echo "Template already patched, skipping: $tpl"
		return 0
	fi

	cp -f "$tpl" "$tpl.antweb_ssh_migrate.bak"

	# Insert the snippet right before the first closing </body> tag.
	awk -v start="$inject_marker_start" -v snippet="$inject_snippet" -v end="$inject_marker_end" '
		!done && /<\/body>/ {
			print start
			print snippet
			print end
			done = 1
		}
		{ print }
	' "$tpl.antweb_ssh_migrate.bak" > "$tpl"

	if grep -qF "$inject_marker_start" "$tpl"; then
		echo "Patched $tpl to auto-load the Migrate tab script (backup: $tpl.antweb_ssh_migrate.bak)"
	else
		echo "WARNING: could not find </body> in $tpl, restoring original."
		cp -f "$tpl.antweb_ssh_migrate.bak" "$tpl"
	fi
}

unpatch_template() {
	local tpl="$1"

	if [ -f "$tpl.antweb_ssh_migrate.bak" ]; then
		cp -f "$tpl.antweb_ssh_migrate.bak" "$tpl"
		rm -f "$tpl.antweb_ssh_migrate.bak"
		echo "Restored original $tpl"
	elif grep -qF "$inject_marker_start" "$tpl" 2>/dev/null; then
		sed -i "/$(printf '%s' "$inject_marker_start" | sed 's/[.[\*^$\/()]/\\&/g')/,/$(printf '%s' "$inject_marker_end" | sed 's/[.[\*^$\/()]/\\&/g')/d" "$tpl"
		echo "Removed injected block from $tpl"
	fi
}

#installation
Install()
{

	echo 'Installing...'
	#==================================================================
	#Dependent installation begins

	tpl=$(find_template)
	if [ -n "$tpl" ]; then
		patch_template "$tpl"
	else
		echo 'WARNING: could not locate the aaPanel main template automatically.'
		echo 'The "Migrate" tab will NOT auto-appear in the website Settings modal.'
		echo "To enable it manually, add this line before </body> in your panel's"
		echo 'main template (usually under /www/server/panel/BTPanel/templates/):'
		echo "  $inject_snippet"
		echo 'The plugin still works via its own page (antweb_ssh_migrate -> open) either way.'
	fi

	#Dependency installation ends
	#==================================================================

	echo '================================================'
	echo 'The installation is complete'
}

#Uninstall
Uninstall()
{
	tpl=$(find_template)
	if [ -n "$tpl" ]; then
		unpatch_template "$tpl"
	fi

	rm -rf $install_path
}

#Operational judgment
if [ "${1}" == 'install' ];then
	Install
elif [ "${1}" == 'uninstall' ];then
	Uninstall
else
	echo 'Error!';
fi
