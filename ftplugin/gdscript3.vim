setlocal commentstring=#\ %s

if exists("g:gdscript3_loaded")
    finish
endif
let g:gdscript3_loaded=1

if !has("python3") && !has("python")
    finish
endif

if has("python3")
    let s:pyfile_cmd = "py3file"
    let s:py_cmd = "py3"
else
    let s:pyfile_cmd = "pyfile"
    let s:py_cmd = "py"
endif

execute s:pyfile_cmd . expand('<sfile>:p:h') . "/../python/classes.py"
execute s:pyfile_cmd . expand('<sfile>:p:h') . "/../python/complete.py"

fun! GDScriptComplete(findstart, base)
    if a:findstart == 1
        let line = getline('.')
        let start = col('.') - 1
        " Treat '-' as part of the word when completing in a string.
        if synIDattr(synID(line('.'), col('.')-1, 1), 'name') ==# "gdString"
            let pattern = '[-a-zA-Z0-9_]'
        else
            let pattern = '[a-zA-Z0-9_]'
        endif
        while start > 0 && line[start - 1] =~ pattern
            let start -= 1
        endwhile
        return start
    else
        execute s:py_cmd . " gdscript_complete()"
        if exists("gdscript_completions")
            return gdscript_completions
        else
            return []
        endif
    endif
endfun

" Configure for common completion frameworks.

fun! <SID>Set(name, default)
    if !exists(a:name)
        execute "let " . a:name . " = " . a:default
    endif
endfun

" Deoplete
call <SID>Set("g:deoplete#sources", "{}")
call <SID>Set("g:deoplete#omni#input_patterns", "{}")
let g:deoplete#sources.gdscript3 = ["omni"]
let g:deoplete#omni#input_patterns.gdscript3 = [
    \ '\.|\w+',
    \ '\bextends\s+',
    \ '\bexport\(',
    \ '\bfunc\s+',
    \ '"res://[^"]*'
    \ ]

" SuperTab
let g:SuperTabDefaultCompletionType = "<c-x><c-o>"

if &rtp =~ 'echodoc'
    let s:echodoc_dict = { "name": "gdscript3", "rank": 9 }
    fun! s:echodoc_dict.search(text)
        execute s:py_cmd . " echodoc_search()"
        if exists("echodoc_search_result")
            return echodoc_search_result
        else
            return []
        endif
    endfun
    call echodoc#register('gdscript3', s:echodoc_dict)

    " Reset echodoc cache when exiting insert mode.
    " This fixes an issue where the function signature wouldn't re-appear
    " after exiting and re-entering insert mode.
    au InsertLeave * let b:prev_echodoc = []
endif

" Configure Syntastic checker
let g:syntastic_gdscript3_checkers = ['godot_server']

set omnifunc=GDScriptComplete
