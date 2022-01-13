odoo.define('common_connector_library.InAppCommunity', function (require) {
    "use strict";
    var appsMenu = require('web.AppsMenu');
    var Notification = require('common_connector_library.InAppNotificationWidget');
    var ajax = require('web.ajax');

    appsMenu.include({
        events: _.extend({}, appsMenu.prototype.events, {
            'click #hide_popup': '_onClickHideEpt',
            'click #close_popup': '_onClickCloseEpt',
            'click .hide_notification': '_onClickToggle',
            'click button.update_button': '_upgradeRedirect',
            'click button.read_more': '_onClickReadMore'
        }),

        _onAppsMenuItemClicked: function (ev) {
            this._super.apply(this, arguments);
            this.openNotification(ev)
        },

        openNotification: function (ev) {
            var $target = $(ev.currentTarget);
            var menuID = $target.data('menu-id');
            if (menuID) {
                    ajax.jsonRpc('/app_notification/get_module/', 'call', {
                    menu_id: menuID,
                }).then(function(details){
                    self.details = details;
                    var updates = details.updates;
                    var notification = new Notification(this, true, details);
                    if ((typeof updates === 'object') && updates.length > 0){
                        notification.do_show();
                    }else {
                        notification.do_hide();
                    }
                });
            }
        },

        _onShowHomeMenu: function () {
            this._super.apply(this, arguments);
            if ($("#notify_ept").length > 0) {
                $("#notify_ept").css({"display": "none"});
            }
        },

        _onClickHideEpt: function (ev) {
            $("#notify_ept").fadeOut(500);
            $(".hide_notification").fadeIn(500);
        },

        _onClickToggle: function () {
            $("#notify_ept").fadeIn(500);
            $(".hide_notification").fadeOut(500);
        },

        _upgradeRedirect: function (ev) {
            this._onClickHideEpt();
            if (self.details && self.details.update_url) {
                var win = window.open(self.details.update_url, '_blank');
                if (!win) {
                    console.error("Popup Blocked!!!, You Need to Allow Popup for this Website.");
                }
            }
        },

        _onClickCloseEpt: function(ev) {
            $("#notify_ept").css({'display': 'none'});
            ajax.jsonRpc('/app_notification/deny_update/', 'call', {
                is_notify: false,
                url: this._current_state,
                module_name: self.details && self.details.module_name
            }).then(function(){
                return true;
            });
        },

        _onClickReadMore: function(ev) {
            if (this.action_manager && this.action_manager.actions) {
                var is_current = false;
                var action_id = "common_connector_library.emipro_app_version_detail_action";
                var actions = this.action_manager.actions;
                for (var action in actions) {
                    if (actions[action].xml_id == action_id) {
                        is_current = true;
                        break;
                    }
                }
                if (!is_current) {
                    this.do_action(action_id, {
                        additional_context: {
                            search_default_module_id: self.details.module_id
                        }
                    });
                }
                this._onClickHideEpt();
            }
        }
    });
});