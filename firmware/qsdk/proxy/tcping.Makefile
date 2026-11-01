# SPDX-License-Identifier: GPL-3.0-only
# Recipe adapted from Openwrt-Passwall/openwrt-passwall-packages
# da712cf06cf4e6fd39e147fb36e6ec936003fcc9/tcping/Makefile.
include $(TOPDIR)/rules.mk
PKG_NAME:=tcping
PKG_VERSION:=0.3
PKG_RELEASE:=1
PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/Lienol/tcping.git
PKG_SOURCE_DATE:=2020-07-04
PKG_SOURCE_VERSION:=db9101834732dac9aaa59dbb7fb9c74612dbf723
PKG_MIRROR_HASH:=36776bf64c41d0c2c2aeb79525499532831133f7b5e174fc51e9e2d7202d5776
PKG_LICENSE:=GPL-2.0-only
PKG_LICENSE_FILES:=license.txt
PKG_BUILD_PARALLEL:=1
include $(INCLUDE_DIR)/package.mk
define Package/tcping
  SECTION:=net
  CATEGORY:=Network
  TITLE:=TCP connection latency probe
endef
define Package/tcping/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/tcping $(1)/usr/bin/
endef
$(eval $(call BuildPackage,tcping))
