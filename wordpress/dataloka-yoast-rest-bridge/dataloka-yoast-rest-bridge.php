<?php
/**
 * Plugin Name: Dataloka Yoast REST Bridge
 * Description: Allows authorized editors to update only three Yoast post SEO fields through WordPress REST API if their Yoast version does not already expose them.
 * Version: 1.0.0
 * Requires PHP: 7.4
 * License: GPL-2.0-or-later
 */

defined( 'ABSPATH' ) || exit;

/**
 * Yoast's own API is read-only. WordPress REST post meta can be writable
 * when registered with show_in_rest. New Yoast versions may already do so;
 * this bridge leaves their existing registration untouched.
 */
add_action(
    'init',
    static function () {
        if ( ! defined( 'WPSEO_VERSION' ) ) {
            return;
        }

        $registered = get_registered_meta_keys( 'post', 'post' );
        $keys       = array(
            '_yoast_wpseo_focuskw',
            '_yoast_wpseo_title',
            '_yoast_wpseo_metadesc',
        );

        foreach ( $keys as $key ) {
            if ( ! empty( $registered[ $key ]['show_in_rest'] ) ) {
                continue;
            }

            register_post_meta(
                'post',
                $key,
                array(
                    'type'              => 'string',
                    'single'            => true,
                    'show_in_rest'      => true,
                    'sanitize_callback' => 'sanitize_text_field',
                    'auth_callback'     => static function ( $allowed, $meta_key, $post_id ) {
                        return $post_id > 0 && current_user_can( 'edit_post', $post_id );
                    },
                )
            );
        }
    },
    30
);
