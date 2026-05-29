#!/bin/bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

#Configure the plugin installation directory
install_path=/www/server/panel/plugin/antweb_ssh_migrate

#installation
Install()
{
	
	echo 'Installing...'
	#==================================================================
	#Dependent installation begins


	#Dependency installation ends
	#==================================================================

	echo '================================================'
	echo 'The installation is complete'
}

#Uninstall
Uninstall()
{
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
