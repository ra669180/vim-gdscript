"============================================================================
"File:        godot_server.vim
"Description: GDScript syntax checker plugin for syntastic using godot_server
"Maintainer:  Timur Celik <clktmr@gmail.com>
"License:     This program is free software. It comes without any warranty,
"             to the extent permitted by applicable law. You can redistribute
"             it and/or modify it under the terms of the Do What The Fuck You
"             Want To Public License, Version 2, as published by Sam Hocevar.
"             See http://sam.zoy.org/wtfpl/COPYING for more details.
"============================================================================

if exists('g:loaded_syntastic_gdscript3_godot_server_checker')
    finish
endif
let g:loaded_syntastic_gdscript3_godot_server_checker = 1

let s:save_cpo = &cpo
set cpo&vim

function! SyntaxCheckers_gdscript3_godot_server_GetLocList() dict
    let makeprg = self.makeprgBuild({ 'args': '-s' })

    let errorformat =
        \ '%E%.%#SCRIPT\ ERROR:\ GDScript::reload:\ %.%#1m%m,%Z%>%.%#res://%f:%l%.%#'

    let loclist = SyntasticMake({
        \ 'makeprg': makeprg,
        \ 'errorformat': errorformat,
        \ 'defaults': {'bufnr': bufnr('')} })

    return loclist
endfunction

call g:SyntasticRegistry.CreateAndRegisterChecker({
    \ 'filetype': 'gdscript3',
    \ 'name': 'godot_server'})

let &cpo = s:save_cpo
unlet s:save_cpo

" vim: set sw=4 sts=4 et fdm=marker:
