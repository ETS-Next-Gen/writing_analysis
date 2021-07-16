function treeget(tree, key) {
    /*
      Retrieve an element from a tree with dotted notation

      e.g. treeget(
          {"hello": {"bar":"biff"}},
          "hello.bar"
      )

      If not found, return `none`
      */
       let keylist = key.split(".");
       let subtree = tree;
       for(var i=0; i<keylist.length; i++) {
            if (subtree == null) {
                return null;
            }
	    if (keylist[i] in subtree) {
	        subtree = subtree[keylist[i]];
	    } else {
                if (keylist[i] && keylist[i].indexOf('[')>0) {
                    item = keylist[i].split('[')[0];
                    idx = keylist[i].split('[')[1];
                    idx = idx.split(']')[0];
                    if (item in subtree) {
                        if (subtree[item][idx]!==undefined) {
                            subtree =subtree[item][idx];                       
                        }
                        else {
                            return null;
                        }
                    }
                    else {
                        return null;
                    }
                } else {
                    return null;
                }
	    }
       }
       return subtree;

}


function googledocs_id_from_url(url) {
    /*
      Given a URL like:
        https://docs.google.com/document/d/jkldfhjklhdkljer8934789468976sduiyui34778dey/edit/foo/bar
      extract the associated document ID:
        jkldfhjklhdkljer8934789468976sduiyui34778dey
      Return null if not a valid URL
    */
    var match = url.match(/.*:\/\/docs\.google\.com\/document\/d\/([^\/]*)\/.*/i);
    if(match) {
	return match[1];
    }
    return null;
}

var writing_lasthash = "";
function unique_id() {
    /*
      This function is used to generate a (hopefully) unique ID for
      each event. This isn't designed to be cryptosecure, since an
      untrusted client can set this to whatever it likes in either
      case. If used by a server, it ought to be rehashed with
      server-side info.

      The major planned use is debugging. In the future, this might be
      helpful for things like negotiating with the server too
      (e.g. "Have you seen this event yet?")
    */
    var shaObj = new jsSHA("SHA-256", "TEXT");
    shaObj.update(writing_lasthash);
    shaObj.update(Math.random().toString());
    shaObj.update(Date.now().toString());
    shaObj.update(document.cookie);
    shaObj.update("NaCl"); /* Salt? */
    shaObj.update(window.location.href);
    writing_lasthash = shaObj.getHash("HEX");
    return writing_lasthash;
}
