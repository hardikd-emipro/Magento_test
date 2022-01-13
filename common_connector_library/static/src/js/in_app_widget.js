odoo.define('common_connector_library.InAppNotificationWidget', function (require) {
    "use strict";

    var Widget = require('web.Widget');
    const widgetRegistry = require('web.widget_registry');
    var core = require('web.core');
    var QWeb = core.qweb;

    var InAppEpt = Widget.extend({
        xmlDependencies: ['/common_connector_library/static/src/xml/in_app_notification.xml'],
        template: 'emipro_in_app_notify',
        events: _.extend({}, Widget.prototype.events, {
            'click #hide_popup': '_onClickHideEpt',
            'click #close_popup': '_onClickCloseEpt',
            'click .hide_notification': '_onClickToggle',
            'click button.update_button': '_upgradeRedirect',
            'click button.read_more': '_onClickReadMore'
        }),

        init: function (parent, show, details) {
            this.show = show;
            this.updates = details.updates;
            this.template_data = '';
            if (this.updates && this.updates.length > 0) {
                if (!('emipro_in_app_notify' in QWeb.templates)) {
                    new Promise(async resolve => {
                        QWeb.add_template("/common_connector_library/static/src/xml/in_app_notification.xml")
                    });
                }
                this.template_data = $(QWeb.render(this.template, {
                    updates: this.updates,
                    update_url: details.update_url
                }).trim());
            }
        },

        start: function () {
            return this._super.apply(this, arguments);
        },

        do_show: function (target='.o_action_manager') {
            if (this.show && this.template_data.length > 0) {
                $("div.hide_notification").css({'display': 'none'});
                if ($("#notify_ept") && $("#notify_ept").length == 0) {
                    this.template_data.appendTo(target);
                }
                $("#notify_ept").fadeIn(1000);
            }
        },

        do_hide: function () {
            if (this.show) {
                this.show = false;
                $("#notify_ept").css({"display": "none"});
                $("div.hide_notification").css({'display': 'none'});
            }
        },
    });
    widgetRegistry.add('emipro_in_app_notify', InAppEpt);
    return InAppEpt;
});

